import torch
from torch import Tensor
from torch.nn import ModuleList

from ptytorch.data_structures import Variable, Object2D, Probe, ProbePositions


class ForwardModel(torch.nn.Module):
    
    def __init__(self):
        super().__init__()
        self.optimizable_variables: ModuleList[Variable] = ModuleList()
        
    def register_optimizable_parameters(self):
        raise NotImplementedError

    def forward(self, *args, **kwargs):
        raise NotImplementedError
    
    def post_differentiation_hook(self, *args, **kwargs):
        pass
    
    
class Ptychography2DForwardModel(ForwardModel):
    
    def __init__(
            self, 
            object: Object2D, 
            probe: Probe, 
            probe_positions: ProbePositions, 
            *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.object = object
        self.probe = probe
        self.probe_positions = probe_positions
                
        self.register_optimizable_parameters()
        
    def register_optimizable_parameters(self):
        for var in [self.object, self.probe, self.probe_positions]:
            if var.optimizable:
                # self.register_parameter(name=var.name, param=torch.nn.Parameter(var.tensor))
                self.optimizable_variables.append(var)

    def forward(self, positions: Tensor, return_object_patches: bool = False) -> Tensor:
        """Run ptychographic forward simulation and calculate the measured intensities.

        :param patterns: A (N, H, W) tensor of diffraction patterns in the batch.
        :param positions: A (N, 2) tensor of probe positions in pixels.
        :return: measured intensities (squared magnitudes).
        """
        y = 0.0
        obj_patches = self.object.extract_patches(positions, self.probe.get_spatial_shape())
        for i_probe_mode in range(self.probe.n_modes):
            p = self.probe.get_mode(i_probe_mode)
            psi = obj_patches * p
            psi_far = torch.fft.fft2(psi, norm='ortho')
            psi_far = torch.fft.fftshift(psi_far, dim=(-2, -1))
            y = y + torch.abs(psi_far) ** 2
                    
        returns = [y]
        if return_object_patches:
            returns.append(obj_patches)
        if len(returns) == 1:
            return returns[0]
        else:
            return returns
        
    def post_differentiation_hook(self, *data_and_label, **kwargs):
        patterns = data_and_label[-1]
        self.scale_gradients(patterns)
    
    def scale_gradients(self, patterns):
        """
        Scale the gradients of object and probe so that they are identical to the
        update functions of ePIE. 
        
        For object, the ePIE update function is
        
            o = o + alpha * p.conj() / (abs(p) ** 2).max() * (psi_prime - psi)
            
        while the gradient given by AD when using MSELoss(reduction="mean") is 
        
            -(1 / (batch_size * h * w)) * alpha * p.conj() * (psi_prime - psi)
            
        To scale the AD gradient to match ePIE, we should
        (1) multiply it by batch_size * h * w;
        (2) divide it by (abs(p) ** 2).max() to make up the ePIE scaling factor.
        
        For probe, the ePIE update function is
        
            p = p + alpha * mean(o.conj() / (abs(o) ** 2).max() * (psi_prime - psi), axis=0)
            
        while the gradient given by AD when using MSELoss(reduction="mean") is 
        
            -(1 / (batch_size * h * w)) * alpha * sum(o.conj() * (psi_prime - psi), axis=0)
            
        To scale the AD gradient to match ePIE, we should
        (1) multiply it by batch_size * h * w;
        (2) divide it by (abs(o) ** 2).max() to make up the ePIE scaling factor 
            (but we can assume this is 1.0);
        (3) divide it by batch_size to make up the mean over the batch dimension.
        """
        # Directly modify the gradients here. Tensor.register_hook has memory leak issue.
        self.object.tensor.data.grad = \
            self.object.tensor.data.grad / self.probe.get_all_mode_intensity().max() \
                * patterns.numel()
        # Assuming (obj_patches.abs() ** 2).max() == 1.0
        self.probe.tensor.data.grad = \
            self.probe.tensor.data.grad * (patterns.numel() / len(patterns))
        