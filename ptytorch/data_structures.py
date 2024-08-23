from typing import Optional, Union, Tuple, Type

import torch
from torch import Tensor
import numpy as np
from numpy import ndarray

import ptytorch.image_proc as ip
from ptytorch.utils import to_tensor


class Variable:
    
    name = None
    optimizable: bool = True
    tensor: Optional[Tensor] = None
    optimizer = None
    
    def __init__(self, 
                 shape: Optional[Tuple[int, ...]] = None, 
                 data: Optional[Union[Tensor, ndarray]] = None, 
                 name: Optional[str] = None, 
                 optimizable: bool = True,
                 optimizer_class: Optional[Type[torch.optim.Optimizer]] = None,
                 optimizer_params: Optional[dict] = None) -> None:
        assert shape is not None or data is not None
        self.optimizable = optimizable
        self.name = name
        self.optimizer_class = optimizer_class
        self.optimizer_params = {} if optimizer_params is None else optimizer_params
        self.optimizer = None
        
        if shape is not None:
            self.tensor = torch.zeros(shape).requires_grad_(optimizable)
        else:
            self.tensor = to_tensor(data).requires_grad_(optimizable)
        self.shape = self.tensor.shape
        
        self.build_optimizer()
            
    def build_optimizer(self):
        if self.optimizable and self.optimizer_class is None:
            raise ValueError("optimizer_class must be specified if optimizable is True.")
        if self.optimizable:
            self.optimizer = self.optimizer_class([self.tensor], **self.optimizer_params)
            
    def set_optimizable(self, optimizable):
        self.optimizable = optimizable
        self.tensor.requires_grad_(optimizable)
    
    
class Object(Variable):
    
    pixel_size_m: float = 1.0
    
    def __init__(self, *args, pixel_size_m: float = 1.0, name='object', **kwargs):
        super().__init__(*args, name=name, **kwargs)
        self.pixel_size_m = pixel_size_m
        self.center_pixel = torch.tensor(self.shape, device=torch.get_default_device()) / 2.0

    def extract_patches(self, positions, patch_shape, *args, **kwargs):
        raise NotImplementedError
        

class Object2D(Object):
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
    def extract_patches(self, positions: Tensor, patch_shape: Tuple[int, int]):
        """Extract patches from 2D object.

        :param positions: a tensor of shape (N, 2) giving the center positions of the patches in pixels.
        :param patch_shape: a tuple giving the patch shape in pixels.
        """
        # Positions are provided with the origin in the center of the object support. 
        # We shift the positions so that the origin is in the upper left corner.
        positions = positions + self.center_pixel
        patches = ip.extract_patches_fourier_shift(self.tensor, positions, patch_shape)
        return patches
        
        
class Probe(Variable):
    
    n_modes = 1
    
    def __init__(self, *args, name='probe', **kwargs):
        super().__init__(*args, name=name, **kwargs)
        self.n_modes = self.tensor.shape[0]
        
    def shift(self, shifts: Tensor):
        """Generate shifted probe. 

        :param shifts: A tensor of shape (2,) or (N, 2) giving the shifts in pixels.
            If a (N, 2)-shaped tensor is given, a batch of shifted probes are generated.
        """
        if shifts.ndim == 1:
            shifted_probe = ip.fourier_shift(self.tensor[None, ...], shifts[None, :])[0]
        else:
            shifted_probe = ip.fourier_shift(self.tensor[None, ...].repeat(shifts.shape[0], 1, 1), shifts)
        return shifted_probe

    def get_mode(self, mode: int):
        return self.tensor[mode]
    
    def get_spatial_shape(self):
        return self.tensor.shape[-2:]


class ProbePositions(Variable):
    
    pixel_size_m: float = 1.0
    conversion_factor_dict = {'nm': 1e9, 'um': 1e6, 'm': 1.0}
        
    def __init__(self, *args, pixel_size_m: float = 1.0, name: str = 'probe_positions', **kwargs):
        """Probe positions. 

        :param data: a tensor of shape (N, 2) giving the probe positions in pixels. 
            Input positions should be in row-major order, i.e., y-posiitons come first.
        """
        super().__init__(*args, name=name, **kwargs)
        self.pixel_size_m = pixel_size_m
        
    def get_positions_in_physical_unit(self, unit: str = 'm'):
        return self.tensor * self.pixel_size_m * self.conversion_factor_dict[unit]
    
