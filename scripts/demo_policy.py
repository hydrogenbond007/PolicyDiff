"""Recorded scripted actions, NOT a learned policy or a general LIBERO solver."""
import json

POLICYDIFF_ABI = 'libero-panda-rgb128-proprio-osc7-v1'


class ReplayPolicy:
    def __init__(self, actions, disable_gripper=False):
        self.actions, self.disable_gripper = actions, disable_gripper

    def reset(self, *, instruction, seed, max_steps):
        self.index = 0

    def act(self, observation):
        action = list(self.actions[self.index]) if self.index < len(self.actions) else [0, 0, 0, 0, 0, 0, -1]
        self.index += 1
        if self.disable_gripper:
            action[-1] = -1
        return action


def load_policy(checkpoint_path, options):
    return ReplayPolicy(json.loads(checkpoint_path.read_text())['actions'], **options)
