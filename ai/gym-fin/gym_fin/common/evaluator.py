# AIPlanner - Deep Learning Financial Planner
# Copyright (C) 2018 Gordon Irlam
#
# All rights reserved. This program may not be used, copied, modified,
# or redistributed without permission.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the
# implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
# PURPOSE.

import csv
import json
import os
import time
from itertools import chain
from math import ceil, sqrt
from random import getstate, seed, setstate
from statistics import mean, stdev, StatisticsError

import numpy as np

from baselines import logger

def weighted_percentiles(value_weights, pctls):
    if len(value_weights[0]) == 0:
        return [float('nan')] * len(pctls)
    results = []
    pctls = list(pctls)
    tot = sum(value_weights[1])
    weight = 0
    for v, w in zip(*value_weights):
        weight += w
        if weight >= pctls[0] / 100 * tot:
            results.append(v)
            pctls.pop(0)
            if not pctls:
                return results
    while pctls:
        results.append(v)
        pctls.pop()
    return results

def weighted_mean(value_weights):
    n = 0
    s = 0
    for value, weight in zip(*value_weights):
        n += weight
        s += weight * value
    try:
        return s / n
    except ZeroDivisionError:
        return float('nan')

def weighted_stdev(value_weights):
    n0 = 0
    n = 0
    s = 0
    ss = 0
    for value, weight in zip(*value_weights):
        if weight != 0:
            n0 += 1
        n += weight
        s += weight * value
        ss += weight * value ** 2
    try:
        return sqrt(n0 / (n0 - 1) * (n * ss - s ** 2) / (n ** 2))
    except ValueError:
        return 0
    except ZeroDivisionError:
        return float('nan')

def weighted_ppf(value_weights, q):
    if len(value_weights[0]) == 0:
        return float('nan')
    n = 0
    ppf = 0
    for value, weight in zip(*value_weights):
        n += weight
        if value <= q:
            ppf += weight
    return ppf / n * 100

def pack_value_weights(value_weights):

    if value_weights:
        return tuple(np.array(x) for x in zip(*value_weights))
    else:
        return [np.array(())] * 2

def unpack_value_weights(value_weights):

    return tuple(tuple(x) for x in zip(*value_weights))

class Evaluator(object):

    def __init__(self, eval_envs, eval_seed, eval_num_timesteps, *,
        remote_evaluators = None, render = False, eval_batch_monitor = False, num_trace_episodes = 0, pdf_buckets = 10):

        self.tstart = time.time()

        self.eval_envs = eval_envs
        self.eval_seed = eval_seed
        self.eval_num_timesteps = eval_num_timesteps
        self.remote_evaluators = remote_evaluators
        self.eval_render = render
        self.eval_batch_monitor = eval_batch_monitor # Unused.
        self.num_trace_episodes = num_trace_episodes
        self.pdf_buckets = pdf_buckets

        if self.remote_evaluators:
            self.eval_num_timesteps = ceil(self.eval_num_timesteps / len(self.remote_evaluators))
            self.num_trace_episodes = ceil(self.num_trace_episodes / len(self.remote_evaluators))

        self.trace = []
        self.episode = {}

    def trace_step(self, i, env, action, done):

        try:
            episode = self.episode[i]
        except KeyError:
            episode = {}
            self.episode[i] = episode

        if not done:
            decoded_action = env.interpret_action(action)
            self.no_aa = [None] * len(decoded_action['asset_allocation'].as_list())
        for item, value in (
                    ('age', env.age),
                    ('alive_count', env.alive_count[env.episode_length]),
                    ('pv_income', env.gi_sum() if not done else None),
                    ('portfolio_wealth', env.p_sum()),
                    ('consume', decoded_action['consume'] if not done else None),
                    ('real_spias_purchase', decoded_action['real_spias_purchase'] if not done else None),
                    ('nominal_spias_purchase', decoded_action['nominal_spias_purchase'] if not done else None),
                    ('asset_allocation', decoded_action['asset_allocation'].as_list() if not done else self.no_aa),
        ):
            try:
                episode[item].append(value)
            except KeyError:
                episode[item] = [value]

        if done:
            self.trace.append(episode)
            del self.episode[i]

    def evaluate(self, pi):

        def rollout(eval_envs, pi):

            envs = tuple(eval_env.unwrapped for eval_env in eval_envs)
            rewards = []
            erewards = []
            estates = []
            obss = [eval_env.reset() for eval_env in eval_envs]
            et = 0
            e = 0
            s = 0
            erews = [0 for _ in eval_envs]
            eweights = [0 for _ in eval_envs]
            weight_sum = 0
            consume_mean = 0
            consume_m2 = 0
            finished = [self.eval_num_timesteps == 0 for _ in eval_envs]
            while True:
                actions = pi(obss)
                if et < self.num_trace_episodes:
                    for i in range(len(eval_envs)):
                        self.trace_step(i, envs[i], actions[i], False)
                if self.eval_render:
                    eval_envs[0].render()
                for i, (eval_env, env, action) in enumerate(zip(eval_envs, envs, actions)):
                    if not finished[i]:
                        obs, r, done, info = eval_env.step(action)
                        s += 1
                        weight = env.reward_weight
                        consume = env.reward_consume
                        reward = env.reward_value
                        estates.append((env.estate_value, env.estate_weight))
                        if weight != 0:
                            rewards.append((reward, weight))
                            erews[i] += reward * weight
                            eweights[i] += weight
                            # https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance
                            weight_sum += weight
                            delta = consume - consume_mean
                            consume_mean += (weight / weight_sum) * delta
                            delta2 = consume - consume_mean
                            consume_m2 += weight * delta * delta2
                        if done:
                            if et < self.num_trace_episodes:
                                self.trace_step(i, env, None, done)
                                et += 1
                            e += 1
                            try:
                                er = erews[i] / eweights[i]
                            except ZeroDivisionError:
                                er = 0
                            erewards.append((er, eweights[i]))
                            erews[i] = 0
                            eweights[i] = 0
                            if i == 0 and self.eval_render:
                                eval_env.render()
                            obss[i] = eval_env.reset()
                            if s >= self.eval_num_timesteps:
                                finished[i] = True
                        else:
                            obss[i] = obs
                if all(finished):
                    break

            return pack_value_weights(sorted(rewards)), pack_value_weights(sorted(erewards)), pack_value_weights(sorted(estates)), \
                weight_sum, consume_mean, consume_m2, self.trace

        self.object_ids = None
        self.exception = None

        if self.eval_envs == None:

            return False

        elif self.remote_evaluators and self.eval_num_timesteps > 0:

            # Have no control over the random seed used by each remote evaluator.
            # If they are ever always the same, we would be restricted to a single remote evaluator.
            # Currently the remote seed is random, and attempting to set it to something deterministic fails.

            def make_pi(policy_graph):
                return lambda obss: policy_graph.compute_actions(obss)[0]

            # Rllib developer API way:
            #     self.object_ids = [e.apply.remote(lambda e: e.foreach_env(lambda env: rollout([env], make_pi(e.get_policy())))) for e in self.remote_evaluators]
            # Fast way (rollout() batches calls to policy when multiple envs):
            self.object_ids = [e.apply.remote(lambda e: [rollout(e.async_env.get_unwrapped(), make_pi(e.get_policy()))]) for e in self.remote_evaluators]

            return self.object_ids

        else:

            state = getstate()

            seed(self.eval_seed)

            try:
                self.rewards, self.erewards, self.estates, self.weight_sum, self.consume_mean, self.consume_m2, self.trace = rollout(self.eval_envs, pi)
            except Exception as e:
                self.exception = e # Only want to know about failures in one place; later in summarize().

            setstate(state)

            return None

    def summarize(self):

        if self.object_ids:

            import ray

            rollouts = ray.get(self.object_ids)

            rewards, erewards, estates, weight_sums, consume_means, consume_m2s, traces = zip(*chain(*rollouts))
            if len(rewards) > 1:
                self.rewards = pack_value_weights(sorted(chain(*(unpack_value_weights(reward) for reward in rewards))))
                self.erewards = pack_value_weights(sorted(chain(*(unpack_value_weights(ereward) for ereward in erewards))))
                self.estates = pack_value_weights(sorted(chain(*(unpack_value_weights(estate) for estate in estates))))
            else:
                self.rewards = rewards[0]
                self.erewards = erewards[0]
                self.estates = estates[0]

            # https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance
            self.weight_sum = 0
            self.consume_mean = 0
            self.consume_m2 = 0
            for weight_sum, consume_mean, consume_m2 in zip(weight_sums, consume_means, consume_m2s):
                if weight_sum > 0:
                    delta = consume_mean - self.consume_mean
                    self.consume_mean = (self.weight_sum * self.consume_mean + weight_sum * consume_mean) / (self.weight_sum + weight_sum)
                    self.consume_m2 += consume_m2 + delta ** 2 * self.weight_sum * weight_sum / (self.weight_sum + weight_sum)

            self.trace = tuple(chain(*traces))[:self.num_trace_episodes]

        else:

            if self.exception:
                raise self.exception

        rew = weighted_mean(self.erewards)
        try:
            std = weighted_stdev(self.erewards)
        except ZeroDivisionError:
            std = float('nan')
        try:
            stderr = std / sqrt(len(self.erewards[0]))
                # Standard error is ill-defined for a weighted sample.
                # Here we are incorrectly assuming each episode carries equal weight.
                # Use erewards rather than rewards because episode rewards are correlated.
        except ZeroDivisionError:
            stderr = float('nan')
        env = self.eval_envs[0].unwrapped
        env.reset()
        utility = env.utility
        unit_ce = indiv_ce = utility.inverse(rew)
        unit_ce_stderr = indiv_ce_stderr = indiv_ce - utility.inverse(rew - stderr)
        ce_min, indiv_low, indiv_high, ce_max = (utility.inverse(u) for u in weighted_percentiles(self.rewards, [2, 10, 90, 98]))
        unit_low = indiv_low
        unit_high = indiv_high

        unit_consume_mean = indiv_consume_mean = self.consume_mean
        try:
            unit_consume_stdev = indiv_consume_stdev = sqrt(self.consume_m2 / (self.weight_sum - 1))
        except (ValueError, ZeroDivisionError):
            unit_consume_stdev = indiv_consume_stdev = float('nan')

        utility_preretirement = utility.utility(env.params.consume_preretirement)
        preretirement_ppf = weighted_ppf(self.rewards, utility_preretirement) / 100

        consume_preretirement = env.params.consume_preretirement

        ce_step = max((ce_max - ce_min) / self.pdf_buckets, ce_max /  1000)
        consume_pdf = self.pdf('consume', self.rewards, 0, ce_max, ce_step, utility.utility, 1 + env.paras.consume_additional if env.sex2 != None else 1)

        estate_max, = weighted_percentiles(self.estates, [98])
        estate_step = estate_max / self.pdf_buckets
        estate_pdf = self.pdf('estate', self.estates, 0, estate_max, estate_step)

        couple = env.sex2 != None
        if couple:
            unit_ce *= 1 + env.params.consume_additional
            unit_ce_stderr *= 1 + env.params.consume_additional
            unit_low *= 1 + env.params.consume_additional
            unit_high *= 1 + env.params.consume_additional
            unit_consume_mean *= 1 + env.params.consume_additional
            unit_consume_stdev *= 1 + env.params.consume_additional

        return {
            'couple': couple,
            'ce': unit_ce,
            'ce_stderr': unit_ce_stderr,
            'consume10': unit_low,
            'consume90': unit_high,
            'consume_mean': unit_consume_mean,
            'consume_stdev': unit_consume_stdev,
            'ce_individual': indiv_ce,
            'ce_stderr_individual': indiv_ce_stderr,
            'consume10_individual': indiv_low,
            'consume90_individual': indiv_high,
            'consume_preretirement': consume_preretirement,
            'consume_preretirement_ppf': preretirement_ppf,
            'consume_pdf': consume_pdf,
            'estate_pdf': estate_pdf,
            'paths': self.trace,
        }

    def pdf(self, what, value_weights, low, high, step, f = lambda x: x, multiplier = 1):

        pdf_bucket_weights = []
        w_tot = 0
        c_ceil = low
        u_ceil = f(c_ceil)
        for r, w in zip(*value_weights):
            while r >= u_ceil:
                if c_ceil >= high * (1 - 1e-15):
                    break
                pdf_bucket_weights.append(0)
                u_floor = u_ceil
                c_ceil += step
                u_ceil = f(c_ceil)
            if u_floor <= r < u_ceil:
                pdf_bucket_weights[-1] += w
            w_tot += w
        pdf = {what: [], 'weight': []}
        for bucket, w in enumerate(pdf_bucket_weights):
            unit_c = step * (bucket + 0.5) * multiplier
            try:
                w_ratio = w / w_tot
            except ZeroDivisionError:
                w_ratio = float('nan')
            pdf[what].append(unit_c)
            pdf['weight'].append(w_ratio)

        return pdf
