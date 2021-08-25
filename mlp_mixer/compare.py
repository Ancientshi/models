import oneflow as flow
import torch
import torch.nn as nn
import numpy as np
from model.mixer import MlpMixer as flow_mlp
from model.torch_mixer import MlpMixer as torch_mlp

pytorch_weight = "./weight/torch/mixer_b16_224.pth"

def oneflow_weight_load(model, checkpoint_path):
    state_dict = torch.load(checkpoint_path)
    new_parameters = dict()
    for key, value in state_dict.items():
        if "num_batches_tracked" not in key:
            val = value.detach().cpu().numpy()
            new_parameters[key] = val.astype(np.float32)
    model.load_state_dict(new_parameters)
    print("Load pretrained weights from {}".format(checkpoint_path))
    return model.state_dict()

def torch_weight_load(model, checkpoint_path):
    state_dict = torch.load(checkpoint_path)
    model.load_state_dict(state_dict)
    return model.state_dict()

def compare(torch_dict, of_dict):
    for torch_key, of_key in zip(torch_dict, of_dict):
        value = torch_dict[torch_key].numpy() - of_dict[of_key].numpy()
        if value.mean() != 0.0:
            print(torch_key)

# create model
of_model = flow_mlp(patch_size=16, num_blocks=12, embed_dim=768)
torch_model = torch_mlp(patch_size=16, num_blocks=12, embed_dim=768)

# load weight
of_state = oneflow_weight_load(of_model, pytorch_weight)
torch_state = torch_weight_load(torch_model, pytorch_weight)

# compare weight
compare(torch_state, of_state)
