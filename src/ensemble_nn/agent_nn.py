"""Agents for neural net bandit problems.

We implement three main types of agent:
  - epsilon-greedy (fixed epsilon, annealing epsilon)
  - dropout (arXiv:1506.02142)
  - ensemble sampling

All code is specialized to the setting of 2-layer fully connected MLPs.
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import numpy as np
import numpy.random as rd

from base.agent import Agent
from .env_nn import TwoLayerNNBandit


class TwoLayerNNEpsilonGreedy(Agent):

  def __init__(self,
               input_dim,
               hidden_dim,
               actions,
               time_horizon,
               prior_var,
               noise_var,
               epsilon_param=0.0,
               learning_rate=1e-1,
               num_gradient_steps=1,
               batch_size=64,
               lr_decay=1,
               leaky_coeff=0.01):
    """Epsilon-greedy agent with two-layer neural network model.

    Args:
      input_dim: int dimension of input.
      hidden_dim: int size of hidden layer.
      actions: numpy array of valid actions (generated by environment).
      time_horizon: int size to pre-allocate data storage.
      prior_var: prior variance for random initialization.
      noise_var: noise variance for update.
      epsilon_param: fixed epsilon choice.
      learning_rate: sgd learning rate.
      num_gradient_steps: how many sgd to do.
      batch_size: size of batch.
      lr_decay: decay learning rate.
      leaky_coeff: slope of "negative" part of the Leaky ReLU.
    """

    self.W1 = 1e-2 * rd.randn(hidden_dim, input_dim)  # initialize weights
    self.W2 = 1e-2 * rd.randn(hidden_dim)

    self.actions = actions
    self.num_actions = len(actions)
    self.T = time_horizon
    self.prior_var = prior_var
    self.noise_var = noise_var
    self.epsilon_param = epsilon_param
    self.lr = learning_rate
    self.num_gradient_steps = num_gradient_steps  # number of gradient steps we
    # take during each time period
    self.batch_size = batch_size
    self.lr_decay = lr_decay
    self.leaky_coeff = leaky_coeff

    self.action_hist = np.zeros((self.T, input_dim))
    self.reward_hist = np.zeros(self.T)

  def _model_forward(self, input_actions):
    """Neural network forward pass.

    Args:
      input_actions: actions to evaluate (numpy array).

    Returns:
      out: network prediction.
      cache: tuple holding intermediate activations for backprop.
    """
    affine_out = np.sum(input_actions[:, np.newaxis, :] * self.W1, axis=2)
    relu_out = np.maximum(self.leaky_coeff * affine_out, affine_out)
    out = np.sum(relu_out * self.W2, axis=1)
    cache = (input_actions, affine_out, relu_out)
    return out, cache

  def _model_backward(self, out, cache, y):
    """Neural network backward pass (for backpropagation).

    Args:
      out: output of batch of predictions.
      cache: intermediate activations from _model_forward.
      y: target labels.

    Returns:
      dW1: gradients for layer 1.
      dW2: gradients for layer 2.
    """
    input_actions, affine_out, relu_out = cache
    dout = -(2 / self.noise_var) * (y - out)
    dW2 = np.sum(dout[:, np.newaxis] * relu_out, axis=0)
    drelu_out = dout[:, np.newaxis] * self.W2
    mask = (affine_out >= 0) + self.leaky_coeff * (affine_out < 0)
    daffine_out = mask * drelu_out
    dW1 = np.dot(daffine_out.T, input_actions)
    return dW1, dW2

  def _update_model(self, t):
    """Update the model by taking a few gradient steps."""
    for i in range(self.num_gradient_steps):
      # sample minibatch
      batch_ind = rd.randint(t + 1, size=self.batch_size)
      action_batch = self.action_hist[batch_ind]
      reward_batch = self.reward_hist[batch_ind]

      out, cache = self._model_forward(action_batch)
      dW1, dW2 = self._model_backward(out, cache, reward_batch)
      dW1 /= self.batch_size
      dW2 /= self.batch_size
      dW1 += 2 / (self.prior_var * (t + 1)) * self.W1
      dW2 += 2 / (self.prior_var * (t + 1)) * self.W2

      self.W1 -= self.lr * dW1
      self.W2 -= self.lr * dW2

  def update_observation(self, observation, action, reward):
    """Learn from observations."""
    t = observation
    self.action_hist[t] = self.actions[action]
    self.reward_hist[t] = reward
    self._update_model(t)
    self.lr *= self.lr_decay

  def pick_action(self, observation):
    """Fixed epsilon-greedy action selection."""
    u = rd.rand()
    if u < self.epsilon_param:
      action = rd.randint(self.num_actions)
    else:
      model_out, _ = self._model_forward(self.actions)
      action = np.argmax(model_out)
    return action


class TwoLayerNNEpsilonGreedyAnnealing(TwoLayerNNEpsilonGreedy):
  """Epsilon-greedy with an annealing epsilon:

  epsilon = self.epsilon_param / (self.epsilon_param + t)
  """

  def pick_action(self, observation):
    """Overload pick_action to dynamically recalculate epsilon-greedy."""
    t = observation
    epsilon = self.epsilon_param / (self.epsilon_param + t)
    u = rd.rand()
    if u < epsilon:
      action = rd.randint(self.num_actions)
    else:
      model_out, _ = self._model_forward(self.actions)
      action = np.argmax(model_out)
    return action


class TwoLayerNNDropout(TwoLayerNNEpsilonGreedy):
  """Dropout is used to represent model uncertainty.
  ICML paper suggests this is Bayesian uncertainty:  arXiv:1506.02142.
  Follow up work suggests that this is flawed: TODO(iosband) add link.
  """

  def __init__(self,
               input_dim,
               hidden_dim,
               actions,
               time_horizon,
               prior_var,
               noise_var,
               drop_prob=0.5,
               learning_rate=1e-1,
               num_gradient_steps=1,
               batch_size=64,
               lr_decay=1,
               leaky_coeff=0.01):
    """Dropout agent with two-layer neural network model.

    Args:
      input_dim: int dimension of input.
      hidden_dim: int size of hidden layer.
      actions: numpy array of valid actions (generated by environment).
      time_horizon: int size to pre-allocate data storage.
      prior_var: prior variance for random initialization.
      noise_var: noise variance for update.
      drop_prob: probability of randomly zero-ing out weight component.
      learning_rate: sgd learning rate.
      num_gradient_steps: how many sgd to do.
      batch_size: size of batch.
      lr_decay: decay learning rate.
      leaky_coeff: slope of "negative" part of the Leaky ReLU.
    """

    self.W1 = 1e-2 * rd.randn(hidden_dim, input_dim)
    self.W2 = 1e-2 * rd.randn(hidden_dim)

    self.actions = actions
    self.num_actions = len(actions)
    self.T = time_horizon
    self.prior_var = prior_var
    self.noise_var = noise_var
    self.p = drop_prob
    self.lr = learning_rate
    self.num_gradient_steps = num_gradient_steps
    self.batch_size = batch_size
    self.lr_decay = lr_decay
    self.leaky_coeff = leaky_coeff

    self.action_hist = np.zeros((self.T, input_dim))
    self.reward_hist = np.zeros(self.T)

  def _model_forward(self, input_actions):
    """Neural network forward pass.

    Note that dropout remains "on" so that forward pass is stochastic.

    Args:
      input_actions: actions to evaluate (numpy array).

    Returns:
      out: network prediction.
      cache: tuple holding intermediate activations for backprop.
    """
    affine_out = np.sum(input_actions[:, np.newaxis, :] * self.W1, axis=2)
    relu_out = np.maximum(self.leaky_coeff * affine_out, affine_out)
    dropout_mask = rd.rand(*relu_out.shape) > self.p
    dropout_out = relu_out * dropout_mask
    out = np.sum(dropout_out * self.W2, axis=1)
    cache = (input_actions, affine_out, relu_out, dropout_mask, dropout_out)
    return out, cache

  def _model_backward(self, out, cache, y):
    """Neural network backward pass (for backpropagation).

    Args:
      out: output of batch of predictions.
      cache: intermediate activations from _model_forward.
      y: target labels.

    Returns:
      dW1: gradients for layer 1.
      dW2: gradients for layer 2.
    """
    input_actions, affine_out, relu_out, dropout_mask, dropout_out = cache
    dout = -(2 / self.noise_var) * (y - out)
    dW2 = np.sum(dout[:, np.newaxis] * relu_out, axis=0)
    ddropout_out = dout[:, np.newaxis] * self.W2
    drelu_out = ddropout_out * dropout_mask
    relu_mask = (affine_out >= 0) + self.leaky_coeff * (affine_out < 0)
    daffine_out = relu_mask * drelu_out
    dW1 = np.dot(daffine_out.T, input_actions)
    return dW1, dW2

  def pick_action(self, observation):
    """Select the greedy action according to the output of a stochastic
    forward pass."""
    model_out, _ = self._model_forward(self.actions)
    action = np.argmax(model_out)
    return action


class TwoLayerNNEnsembleSampling(Agent):
  """An ensemble sampling agent maintains an ensemble of neural nets, each
  fitted to a perturbed prior and perturbed observations."""

  def __init__(self,
               input_dim,
               hidden_dim,
               actions,
               time_horizon,
               prior_var,
               noise_var,
               num_models=10,
               learning_rate=1e-1,
               num_gradient_steps=1,
               batch_size=64,
               lr_decay=1,
               leaky_coeff=0.01):
    """Ensemble sampling agent with two-layer neural network model.

    Args:
      input_dim: int dimension of input.
      hidden_dim: int size of hidden layer.
      actions: numpy array of valid actions (generated by environment).
      time_horizon: int size to pre-allocate data storage.
      prior_var: prior variance for random initialization.
      noise_var: noise variance for update.
      num_models: Number of ensemble models to train.
      learning_rate: sgd learning rate.
      num_gradient_steps: how many sgd to do.
      batch_size: size of batch.
      lr_decay: decay learning rate.
      leaky_coeff: slope of "negative" part of the Leaky ReLU.
    """

    self.M = num_models

    # initialize models by sampling perturbed prior means
    self.W1_model_prior = np.sqrt(prior_var) * rd.randn(self.M, hidden_dim,
                                                        input_dim)
    self.W2_model_prior = np.sqrt(prior_var) * rd.randn(self.M, hidden_dim)
    self.W1 = np.copy(self.W1_model_prior)
    self.W2 = np.copy(self.W2_model_prior)

    self.actions = actions
    self.num_actions = len(actions)
    self.T = time_horizon
    self.prior_var = prior_var
    self.noise_var = noise_var
    self.lr = learning_rate
    self.num_gradient_steps = num_gradient_steps
    self.batch_size = batch_size
    self.lr_decay = lr_decay
    self.leaky_coeff = leaky_coeff

    self.action_hist = np.zeros((self.T, input_dim))
    self.model_reward_hist = np.zeros((self.M, self.T))

  def _model_forward(self, m, input_actions):
    """Neural network forward pass for single model of ensemble.

    Args:
      m: index of which network to evaluate.
      input_actions: actions to evaluate (numpy array).

    Returns:
      out: network prediction.
      cache: tuple holding intermediate activations for backprop.
    """
    affine_out = np.sum(input_actions[:, np.newaxis, :] * self.W1[m], axis=2)
    relu_out = np.maximum(self.leaky_coeff * affine_out, affine_out)
    out = np.sum(relu_out * self.W2[m], axis=1)
    cache = (input_actions, affine_out, relu_out)
    return out, cache

  def _model_backward(self, m, out, cache, y):
    """Neural network backward pass (for backpropagation) for single network.

    Args:
      m: index of which network to evaluate.
      out: output of batch of predictions.
      cache: intermediate activations from _model_forward.
      y: target labels.

    Returns:
      dW1: gradients for layer 1.
      dW2: gradients for layer 2.
    """
    input_actions, affine_out, relu_out = cache
    dout = -(2 / self.noise_var) * (y - out)
    dW2 = np.sum(dout[:, np.newaxis] * relu_out, axis=0)
    drelu_out = dout[:, np.newaxis] * self.W2[m]
    mask = (affine_out >= 0) + self.leaky_coeff * (affine_out < 0)
    daffine_out = mask * drelu_out
    dW1 = np.dot(daffine_out.T, input_actions)
    return dW1, dW2

  def _update_model(self, m, t):
    """Apply SGD to model m."""
    for i in range(self.num_gradient_steps):
      # sample minibatch
      batch_ind = rd.randint(t + 1, size=self.batch_size)
      action_batch = self.action_hist[batch_ind]
      reward_batch = self.model_reward_hist[m][batch_ind]

      out, cache = self._model_forward(m, action_batch)
      dW1, dW2 = self._model_backward(m, out, cache, reward_batch)
      dW1 /= self.batch_size
      dW2 /= self.batch_size

      dW1 += 2 / (self.prior_var * (t + 1)) * (
          self.W1[m] - self.W1_model_prior[m])
      dW2 += 2 / (self.prior_var * (t + 1)) * (
          self.W2[m] - self.W2_model_prior[m])

      self.W1[m] -= self.lr * dW1
      self.W2[m] -= self.lr * dW2
    return

  def update_observation(self, observation, action, reward):
    """Learn from observations, shared across all models.

    However, perturb the reward independently for each model and then update.
    """
    t = observation
    self.action_hist[t] = self.actions[action]

    for m in range(self.M):
      m_noise = np.sqrt(self.noise_var) * rd.randn()
      self.model_reward_hist[m, t] = reward + m_noise
      self._update_model(m, t)

    self.lr *= self.lr_decay

  def pick_action(self, observation):
    """Select action via ensemble sampling.

    Choose active network uniformly at random, then act greedily wrt that model.
    """
    m = rd.randint(self.M)
    model_out, _ = self._model_forward(m, self.actions)
    action = np.argmax(model_out)
    return action
