# AIPlanner - Deep Learning Financial Planner
# Copyright (C) 2018 Gordon Irlam
#
# All rights reserved. This program may not be used, copied, modified,
# or redistributed without permission.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the
# implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
# PURPOSE.

from datetime import datetime
from json import loads
from math import atanh, ceil, exp, floor, isnan, log, sqrt, tanh
from random import seed, random, uniform

import numpy as np

from gym import Env
from gym.spaces import Box

from life_table import LifeTable
from spia import IncomeAnnuity

from gym_fin.envs.asset_allocation import AssetAllocation
from gym_fin.envs.bonds import BondsSet
from gym_fin.envs.policies import policy
from gym_fin.envs.returns import Returns, returns_report, yields_report
from gym_fin.envs.returns_sample import ReturnsSample
from gym_fin.envs.taxes import Taxes
from gym_fin.envs.utility import Utility

class AttributeObject(object):

    def __init__(self, dict):
        self.__dict__.update(dict)

class FinEnv(Env):

    metadata = {'render.modes': ['human']}

    def _compute_q_adjust(self, life_table, sex, age_adjust, age_end, life_expectancy_additional, life_table_date, time_period):

        le_add = 0 if life_table == 'fixed' else life_expectancy_additional
        death_age = age_end - time_period
        table = LifeTable(life_table, sex, age_adjust, death_age = death_age, le_add = le_add, date_str = life_table_date)

        return table.q_adjust

    def _compute_vital_stats(self, age_start, age_start2, q_adjust, q_adjust2):

        death_age = self.params.age_end - self.params.time_period
        table = LifeTable(self.params.life_table, self.params.sex, age_start,
            death_age = death_age, q_adjust = q_adjust, date_str = self.params.life_table_date)
        if self.params.sex2 == None:
            table2 = None
        else:
            table2 = LifeTable(self.params.life_table, self.params.sex2, age_start2,
                death_age = death_age, q_adjust = q_adjust2, date_str = self.params.life_table_date)

        start_date = datetime.strptime(self.params.life_table_date, '%Y-%m-%d')
        this_year = datetime(start_date.year, 1, 1)
        next_year = datetime(start_date.year + 1, 1, 1)
        start_decimal_year = start_date.year + (start_date - this_year) / (next_year - this_year)

        alive_both = [1 if self.params.sex2 else 0]
        alive_one = [0 if self.params.sex2 else 1]
        _alive = 1
        _alive2 = 1

        alive_single = [None if self.params.sex2 else 1]
        _alive_single = None if self.params.sex2 else 1
        dead = False
        dead2 = self.params.sex2 == None
        dead_at = random()
        dead_at2 = random()
        first_dies_first = False

        y = 0
        q_y = -1
        q = 0
        q2 = 0
        remaining_fract = 0
        a_y = self.params.time_period
        while True:
            append_time = a_y - y
            fract = min(remaining_fract, append_time)
            prev_alive = _alive
            prev_alive2 = _alive2
            q_fract = (1 - q) ** fract
            _alive *= q_fract
            q_fract2 = (1 - q2) ** fract
            _alive2 *= q_fract2
            if not (dead or dead2):
                dead = _alive < dead_at
                dead2 = _alive2 < dead_at2
                if dead and dead2:
                    _alive_single = 0
                elif dead:
                    first_dies_first = True
                    _alive_single = q_fract ** ((dead_at - _alive) / (prev_alive - _alive))
                elif dead2:
                    _alive_single = q_fract2 ** ((dead_at2 - _alive2) / (prev_alive2 - _alive2))
            elif dead:
                _alive_single *= q_fract2
            elif dead2:
                _alive_single *= q_fract
            remaining_fract -= fract
            y += fract
            if y >= a_y:
                alive_both.append(_alive * _alive2)
                alive_one.append(1 - _alive * _alive2 - (1 - _alive) * (1 - _alive2))
                alive_single.append(_alive_single)
                a_y += self.params.time_period
            if y - q_y >= 1:
                q_y += 1
                q = table.q(age_start + q_y, year = start_decimal_year + q_y)
                if self.params.sex2:
                    q2 = table2.q(age_start2 + q_y, year = start_decimal_year + q_y)
                else:
                    q2 = 1
                remaining_fract = 1
                if q == q2 == 1:
                    break

        alive_years = (2 * sum(alive_both) + sum(alive_one)) * self.params.time_period

        life_expectancy_both = []
        for y in range(len(alive_both)):
            try:
                le = sum(alive_both[y:]) / alive_both[y] * self.params.time_period
            except ZeroDivisionError:
                le = 0
            life_expectancy_both.append(le)
        life_expectancy_both.append(0)
        life_expectancy_one = []
        for y in range(len(alive_one)):
            try:
                le = sum(alive_one[y:]) / (alive_both[y] + alive_one[y]) * self.params.time_period
            except ZeroDivisionError:
                le = 0
            life_expectancy_one.append(le)
        life_expectancy_one.append(0)
        life_expectancy_single = []
        for y in range(len(alive_single)):
            try:
                le = sum(alive_single[y:]) / alive_single[y] * self.params.time_period
            except TypeError:
                le = None
            except ZeroDivisionError:
                le = 0
            life_expectancy_single.append(le)
        life_expectancy_single.append(0)

        alive_single.append(0)

        return first_dies_first, alive_years, tuple(alive_single), table, table2, \
            tuple(life_expectancy_both), tuple(life_expectancy_one), tuple(life_expectancy_single)

    def __init__(self, bonds_cached = None, action_space_unbounded = False, direct_action = False, **kwargs):

        self.action_space_unbounded = action_space_unbounded
        self.direct_action = direct_action
        self.params = AttributeObject(kwargs)

        self.action_space = Box(low = -1.0, high = 1.0, shape = (10, ), dtype = 'float32')
            # consume_action, spias_action, real_spias_action,
            # stocks_action, real_bonds_action, nominal_bonds_action, iid_bonds_action, bills_action,
            # real_bonds_duration_action, nominal_bonds_duration_action,
            # DDPG implementation assumes [-x, x] symmetric actions.
            # PPO1 implementation ignores size and assumes [-inf, inf] output.
        self.observation_space = Box(
            # Note: Couple status must be observation[0], or else change is_couple in baselines/baselines/ppo1/mlp_policy.py.
            # couple, single, life-expectancy both, life-expectancy one,
            # income present value annualized: tax_free, tax_deferred, taxable,
            # wealth annualized: tax_free, tax_deferred, taxable,
            # short real interest rate, short inflation rate
            low  = np.array((0, 0,   0,   0,   0,   0,   0,   0,   0,   0, -0.05, 0.0)),
            high = np.array((1, 1, 100, 100, 1e6, 1e6, 1e6, 1e6, 1e6, 1e6,  0.05, 0.1)),
            dtype = 'float32'
        )

        self.q_adjust = self._compute_q_adjust(self.params.life_table, self.params.sex, self.params.age_adjust, self.params.age_end,
            self.params.life_expectancy_additional, self.params.life_table_date, self.params.time_period)
        if self.params.sex2:
            self.q_adjust2 = self._compute_q_adjust(self.params.life_table, self.params.sex2, self.params.age_adjust2, self.params.age_end,
                self.params.life_expectancy_additional2, self.params.life_table_date, self.params.time_period)
        else:
            self.q_adjust2 = None

        self.utility = Utility(self.params.gamma, self.params.consume_floor)

        self.stocks = Returns(self.params.stocks_return, self.params.stocks_volatility,
            self.params.stocks_standard_error if self.params.returns_standard_error else 0, self.params.time_period)
        self.iid_bonds = Returns(self.params.iid_bonds_return, self.params.iid_bonds_volatility,
            self.params.bonds_standard_error if self.params.returns_standard_error else 0, self.params.time_period)
        self.bills = Returns(self.params.bills_return, self.params.bills_volatility,
            self.params.bills_standard_error if self.params.returns_standard_error else 0, self.params.time_period)

        self.bonds = bonds_cached if bonds_cached else BondsSet()
        self.bonds.update(
            real_standard_error = self.params.bonds_standard_error if self.params.returns_standard_error else 0,
            inflation_standard_error = self.params.inflation_standard_error if self.params.returns_standard_error else 0,
            time_period = self.params.time_period)
        self.bonds_stepper = self.bonds.nominal

        if self.params.iid_bonds:
            if self.params.iid_bonds_type == 'real':
                self.iid_bonds = ReturnsSample(self.bonds.real, self.params.iid_bonds_duration,
                    self.params.bonds_standard_error if self.params.returns_standard_error else 0,
                    stepper = self.bonds_stepper, time_period = self.params.time_period)
            elif self.params.iid_bonds_type == 'nominal':
                self.iid_bonds = ReturnsSample(self.bonds.nominal, self.params.iid_bonds_duration,
                    self.params.bonds_standard_error if self.params.returns_standard_error else 0,
                    stepper = self.bonds_stepper, time_period = self.params.time_period)

        if self.params.display_returns:

            print()
            print('Real/nominal yields:')

            if self.params.real_bonds:
                if self.params.real_bonds_duration:
                    yields_report('real bonds {:2d}'.format(int(self.params.real_bonds_duration)), self.bonds.real,
                        duration = self.params.real_bonds_duration, stepper = self.bonds_stepper, time_period = self.params.time_period)
                else:
                    yields_report('real bonds  5', self.bonds.real, duration = 5, stepper = self.bonds_stepper, time_period = self.params.time_period)
                    yields_report('real bonds 15', self.bonds.real, duration = 15, stepper = self.bonds_stepper, time_period = self.params.time_period)

            if self.params.nominal_bonds:
                if self.params.nominal_bonds_duration:
                    yields_report('nominal bonds {:2d}'.format(int(self.params.nominal_bonds_duration)), self.bonds.nominal,
                        duration = self.params.nominal_bonds_duration, stepper = self.bonds_stepper, time_period = self.params.time_period)
                else:
                    yields_report('nominal bonds  5', self.bonds.nominal, duration = 5, stepper = self.bonds_stepper, time_period = self.params.time_period)
                    yields_report('nominal bonds 15', self.bonds.nominal, duration = 15, stepper = self.bonds_stepper, time_period = self.params.time_period)

            print()
            print('Real returns:')

            if self.params.stocks:
                returns_report('stocks', self.stocks, time_period = self.params.time_period)

            if self.params.real_bonds:
                if self.params.real_bonds_duration:
                    returns_report('real bonds {:2d}'.format(int(self.params.real_bonds_duration)), self.bonds.real,
                        duration = self.params.real_bonds_duration, stepper = self.bonds_stepper, time_period = self.params.time_period)
                else:
                    returns_report('real bonds  5', self.bonds.real, duration = 5, stepper = self.bonds_stepper, time_period = self.params.time_period)
                    returns_report('real bonds 15', self.bonds.real, duration = 15, stepper = self.bonds_stepper, time_period = self.params.time_period)

            if self.params.nominal_bonds:
                if self.params.nominal_bonds_duration:
                    returns_report('nominal bonds {:2d}'.format(int(self.params.nominal_bonds_duration)), self.bonds.nominal,
                        duration = self.params.nominal_bonds_duration, stepper = self.bonds_stepper, time_period = self.params.time_period)
                else:
                    returns_report('nominal bonds  5', self.bonds.nominal, duration = 5, stepper = self.bonds_stepper, time_period = self.params.time_period)
                    returns_report('nominal bonds 15', self.bonds.nominal, duration = 15, stepper = self.bonds_stepper, time_period = self.params.time_period)

            if self.params.iid_bonds:
                returns_report('iid bonds', self.iid_bonds, time_period = self.params.time_period)

            if self.params.bills:
                returns_report('bills', self.bills, time_period = self.params.time_period)

            if self.params.nominal_bonds or self.params.nominal_spias:
                returns_report('inflation', self.bonds.inflation,
                    duration = self.params.time_period, stepper = self.bonds_stepper, time_period = self.params.time_period)

        self.reset()

    def gi_sum(self):

        gi = 0
        for key, db in self.defined_benefits.items():
            real = key[1]
            payout = db['sched'][0]
            if not real:
                payout /= self.cpi
            gi += payout

        return gi

    def p_sum(self):

        return self.p_tax_free + self.p_tax_deferred + self.p_taxable

    def get_db(self, defined_benefits, type, owner, inflation_adjustment, joint, payout_fraction, type_of_funds):

        key = (type_of_funds, inflation_adjustment == 'cpi', type == 'Social Security', owner, joint, payout_fraction)
        try:
            db = defined_benefits[key]
        except KeyError:

            owner_single = 'spouse' if self.first_dies_first else 'self'
            db = {'owner': owner, 'owner_single': owner_single, 'ignore_schedule': False}
            defined_benefits[key] = db

            younger = self.age if self.params.sex2 == None else min(self.age, self.age2)
            episodes = int(self.params.age_end - younger)

            bonds = self.bonds.real if inflation_adjustment == 'cpi' else self.bonds.nominal
            if self.couple:
                life_table = self.life_table if owner == 'self' else self.life_table2
                life_table2 = self.life_table2 if owner == 'self' else self.life_table
            else:
                life_table = self.life_table2 if self.first_dies_first else self.life_table
                life_table2 = None
            payout_delay = 0
            sched = [0] * episodes
            db['sched'] = sched
            schedule = lambda y: (1 if y >= 1 else 0) if db['ignore_schedule'] else sched[int(y)]
            db['spia'] = IncomeAnnuity(bonds, life_table, life_table2 = life_table2, payout_delay = 12 * payout_delay, joint_contingent = joint,
                joint_payout_fraction = payout_fraction, frequency = 1, cpi_adjust = 'all', date_str = self.params.life_table_date, schedule = schedule)

            if self.couple and self.life_table2:

                life_table = self.life_table2 if self.first_dies_first else self.life_table
                sched_single = [0] * episodes
                db['sched_single'] = sched_single
                schedule = lambda y: (1 if y >= 1 else 0) if db['ignore_schedule'] else sched_single[int(y)]
                db['spia_single'] = IncomeAnnuity(bonds, life_table, payout_delay = 12 * payout_delay,
                    frequency = 1, cpi_adjust = 'all', date_str = self.params.life_table_date, schedule = schedule)

        return db

    def add_sched(self, db, start, end, payout, payout_fraction, inflation_adjustment):

        for e in range(ceil(max(start, 0)), floor(min(end, len(db['sched'])))):
            adjustment = 1 if inflation_adjustment == 'cpi' else (1 + inflation_adjustment) ** e
            db['sched'][e] += payout * adjustment
            try:
                db['sched_single'][e] += payout * payout_fraction * adjustment
            except KeyError:
                pass

    def add_db(self, defined_benefits, type = 'Income Annuity', owner = 'self', age = None, premium = None, payout = None,
        inflation_adjustment = 'cpi', joint = False, payout_fraction = 0, source_of_funds = 'tax_deferred', exclusion_period = 0, exclusion_amount = 0):

        assert owner in ('self', 'spouse')
        owner_age = self.age if owner == 'self' else self.age2
        if age == None:
            age = owner_age
        assert (premium == None) != (payout == None)

        db = self.get_db(defined_benefits, type, owner, inflation_adjustment, joint, payout_fraction, source_of_funds)

        if premium != None:
            mwr = self.params.real_spias_mwr if inflation_adjustment == 'cpi' else self.params.nominal_spias_mwr
            db['ignore_schedule'] = True # Hack.
            db['spia'].set_age(self.age if db['owner'] == 'self' else self.age2) # Forces use of schedule.
            payout = db['spia'].payout(premium, mwr = mwr)
            db['ignore_schedule'] = False
            # Will set_age() back when reset()/step() completes.
            start = 1
        else:
            try:
                payout_low, payout_high = payout
            except TypeError:
                pass
            else:
                payout = self.log_uniform(payout_low, payout_high)

            start = age - owner_age

        if joint or ((owner == 'self') == self.first_dies_first):
            actual_payout_fraction = payout_fraction
        else:
            actual_payout_fraction = 1

        self.add_sched(db, start, float('inf'), payout, actual_payout_fraction, inflation_adjustment)

        if source_of_funds == 'taxable' and exclusion_period > 0:

            # Shift nominal exclusion amount from taxable to tax free income.
            end = start + exclusion_period
            db = self.get_db(defined_benefits, type, owner, 0, joint, payout_fraction, 'taxable')
            self.add_sched(db, start, end, - exclusion_amount, actual_payout_fraction, 0)
            db = self.get_db(defined_benefits, type, owner, 0, joint, payout_fraction, 'tax_free')
            self.add_sched(db, start, end, exclusion_amount, actual_payout_fraction, 0)

    def parse_defined_benefits(self, defined_benefits_json):

        defined_benefits = {}
        for db in loads(defined_benefits_json):
            self.add_db(defined_benefits, **db)
        return defined_benefits

    def log_uniform(self, low, high):
        if low == high:
            return low # Handles low == high == 0.
        else:
            return exp(uniform(log(low), log(high)))

    def reset(self):

        if self.params.reproduce_episode != None:
            self._reproducable_seed(self.params.reproduce_episode, 0, 0)

        age_start = uniform(self.params.age_start_low, self.params.age_start_high)
        age_start2 = uniform(self.params.age_start2_low, self.params.age_start2_high)
        self.first_dies_first, self.alive_years, self.alive_single, self.life_table, self.life_table2, \
            self.life_expectancy_both, self.life_expectancy_one, self.life_expectancy_single = \
            self._compute_vital_stats(age_start, age_start2, self.q_adjust, self.q_adjust2)
        self.age = age_start
        self.age2 = age_start2

        self.couple = self.alive_single[0] == None
        self.defined_benefits = self.parse_defined_benefits(self.params.defined_benefits)
        for db in self.defined_benefits.values():
            db['spia'].set_age(self.age if db['owner'] == 'self' else self.age2) # Pick up non-zero schedule for observe.

        found = False
        for _ in range(1000):

            self.p_tax_free = self.log_uniform(self.params.p_tax_free_low, self.params.p_tax_free_high)
            self.p_tax_deferred = self.log_uniform(self.params.p_tax_deferred_low, self.params.p_tax_deferred_high)
            taxable_assets = AssetAllocation(fractional = False)
            if self.params.stocks:
                taxable_assets.aa['stocks'] = self.log_uniform(self.params.p_taxable_stocks_low, self.params.p_taxable_stocks_high)
            if self.params.real_bonds:
                taxable_assets.aa['real_bonds'] = self.log_uniform(self.params.p_taxable_real_bonds_low, self.params.p_taxable_real_bonds_high)
            if self.params.nominal_bonds:
                taxable_assets.aa['nominal_bonds'] = self.log_uniform(self.params.p_taxable_nominal_bonds_low, self.params.p_taxable_nominal_bonds_high)
            if self.params.iid_bonds:
                taxable_assets.aa['iid_bonds'] = self.log_uniform(self.params.p_taxable_iid_bonds_low, self.params.p_taxable_iid_bonds_high)
            if self.params.bills:
                taxable_assets.aa['bills'] = self.log_uniform(self.params.p_taxable_bills_low, self.params.p_taxable_bills_high)
            self.p_taxable = sum(taxable_assets.aa.values())
            if self.params.p_taxable_stocks_basis_fraction_low == self.params.p_taxable_stocks_basis_fraction_high:
                p_taxable_stocks_basis_fraction = self.params.p_taxable_stocks_basis_fraction_low
            else:
                p_taxable_stocks_basis_fraction = uniform(self.params.p_taxable_stocks_basis_fraction_low, self.params.p_taxable_stocks_basis_fraction_high)

            consume_expect = self.gi_sum() + self.p_sum() / (2 * self.life_expectancy_both[0] + self.life_expectancy_one[0])

            found = self.params.consume_floor <= consume_expect <= self.params.consume_ceiling
            if found:
                break

        if not found:
            raise Exception('Expected consumption falls outside model training range.')

        self.taxes = Taxes(self, taxable_assets, p_taxable_stocks_basis_fraction)
        self.taxes_due = 0

        self.cpi = 1

        self.stocks.reset()
        self.iid_bonds.reset()
        self.bills.reset()

        self.bonds_stepper.reset()

        self.prev_asset_allocation = None
        self.prev_taxable_assets = taxable_assets
        self.prev_real_spias_rate = None
        self.prev_nominal_spias_rate = None
        self.prev_consume_rate = None
        self.prev_reward = None

        self.episode_utility_sum = 0
        self.episode_length = 0

        return self._observe()

    def encode_direct_action(self, consume_fraction, *, real_spias_fraction = None, nominal_spias_fraction = None,
        stocks = None, real_bonds = None, nominal_bonds = None, iid_bonds = None, bills = None,
        real_bonds_duration = None, nominal_bonds_duration = None):

        return (consume_fraction, real_spias_fraction, nominal_spias_fraction,
            AssetAllocation(stocks = stocks, real_bonds = real_bonds, nominal_bonds = nominal_bonds, iid_bonds = iid_bonds, bills = bills),
            real_bonds_duration, nominal_bonds_duration)

    def decode_action(self, action):

        if isnan(action[0]):
            assert False # Detect bug in code interacting with model before it messes things up.

        try:
            action = action.tolist() # De-numpify if required.
        except AttributeError:
            pass

        consume_action, spias_action, real_spias_action, \
            stocks_action, real_bonds_action, nominal_bonds_action, iid_bonds_action, bills_action, \
            real_bonds_duration_action, nominal_bonds_duration_action = action

        if self.action_space_unbounded:
            real_spias_action = tanh(real_spias_action)
            real_bonds_duration_action = tanh(real_bonds_duration_action)
            nominal_bonds_duration_action = tanh(nominal_bonds_duration_action)
        else:
            consume_action = atanh(consume_action)
            spias_action = atanh(spias_action)
            stocks_action = atanh(stocks_action)
            real_bonds_action = atanh(real_bonds_action)
            nominal_bonds_action = atanh(nominal_bonds_action)
            iid_bonds_action = atanh(iid_bonds_action)
            bills_action = atanh(bills_action)

        if self.params.consume_rescale == 'direct':

            # Code interacting with model will fail, as can't handle -inf reward.

            consume_fraction = consume_action / self.p_plus_income()

        elif self.params.consume_rescale == 'positive_direct':

            consume_action = exp(consume_action)
            consume_fraction = consume_action / self.p_plus_income()

        elif self.params.consume_rescale == 'fraction_direct':

            consume_action = tanh(consume_action / 2)
                # Scale back initial volatility of consume_action to improve run to run mean and reduce standard deviation of certainty equivalent.
            consume_fraction = (consume_action + 1) / 2

        elif self.params.consume_rescale == 'fraction_biased':

            consume_action = tanh(consume_action)
            consume_action = (consume_action + 1) / 2
            # consume_action is in the range [0, 1]. Make consume_fraction also in the range [0, 1], but weight consume_fraction towards zero.
            # Otherwise the default is to consume 50% of assets each year. Quickly end up with few assets, making learning difficult.
            #
            #     consume_weight    consume_fraction when consume_action = 0.5
            #          5                         7.6%
            #          6                         4.7%
            #          7                         2.9%
            #          8                         1.8%
            #          9                         1.1%
            consume_weight = 5
            consume_fraction = (exp(consume_weight * consume_action) - 1) / (exp(consume_weight) - 1)

        elif self.params.consume_rescale == 'estimate_biased':

            consume_action = tanh(consume_action / 10)
                # Scale back initial volatility of consume_action to improve run to run mean and reduce standard deviation of certainty equivalent.
            consume_action = (consume_action + 1) / 2
            consume_estimate = self._income_estimate() / self.p_plus_income()
            consume_weight = 2 * log((1 + sqrt(1 - 4 * consume_estimate * (1 - consume_estimate))) / (2 * consume_estimate))
                # So that consume_fraction = consume_estimate when consume_action = 0.5.
            consume_weight = max(1e-3, consume_weight) # Don't allow weight to become zero.
            # consume_action is in the range [0, 1]. Make consume_fraction also in the range [0, 1], but weight consume_fraction towards zero.
            # Otherwise by default consume 50% of assets each year. Quickly end up with few assets, and large negative utilities, making learning difficult.
            consume_fraction = (exp(consume_weight * consume_action) - 1) / (exp(consume_weight) - 1)

        elif self.params.consume_rescale == 'estimate_bounded':

            consume_action = tanh(consume_action / 5)
                # Scaling back initial volatility of consume_action is observed to improve run to run mean and reduce standard deviation of certainty equivalent.
            consume_action = (consume_action + 1) / 2
            # Define a consume floor and consume ceiling outside of which we won't consume.
            # The mid-point acts as a hint as to the initial consumption values to try.
            # With 0.5 as the mid-point (when time_period = 1) we will initially consume on average half the portfolio at each step.
            # This leads to very small consumption at advanced ages. The utilities and thus rewards for these values will be highly negative.
            # For DDPG the resulting reward values will be sampled from the replay buffer, leading to a good DDPG fit for the negative rewards.
            # This will be to the detriment of the fit for more likely reward values.
            # For PPO the policy network either never fully retrains after the initial poor fit, or requires more training time.
            consume_estimate = self._income_estimate() / self.p_plus_income()
            consume_floor = 0
            consume_ceil = 2 * consume_estimate
            consume_fraction = consume_floor + (consume_ceil - consume_floor) * consume_action

        else:

            assert False

        consume_fraction = max(0, min(consume_fraction, 1 / self.params.time_period))

        if self.params.real_spias or self.params.nominal_spias:

            # Try and make it easy to learn the optimal amount of guaranteed income,
            # so things function well with differing current amounts of guaranteed income.

            spias_action = tanh(spias_action / 4)
                # Scaling back initial volatility of spias_action is observed to improve run to run mean and reduce standard deviation of certainty equivalent.
            spias_action = (spias_action + 1) / 2
            current_spias_fraction_estimate = self.gi_sum() / self._income_estimate()
            assert 0 <= current_spias_fraction_estimate <= 1
            # Might like to pass on any more SPIAs when spias_action <= current_spias_fraction_estimate,
            # but that might then make learning to increase spias_action difficult.
            # We thus use a variant of the leaky ReLU.
            def leaky_lu(x):
                '''x in [-1, 1]. Result in [0, 1].'''
                leak = 0 # Disable leak for now as it results in unwanted SPIA purchases.
                return leak + x * (1 - leak) if x > 0 else leak * (1 + x)
            try:
                spias_fraction = leaky_lu(spias_action - current_spias_fraction_estimate) / leaky_lu(1 - current_spias_fraction_estimate)
            except ZeroDivisionError:
                spias_fraction = 0
            assert 0 <= spias_fraction <= 1

            real_spias_fraction = spias_fraction if self.params.real_spias else 0
            if self.params.nominal_spias:
                real_spias_fraction *= (real_spias_action + 1) / 2
            nominal_spias_fraction = spias_fraction - real_spias_fraction

        if self.couple:
            min_age = min(self.age, self.age2)
        else:
            min_age = self.age

        spias_allowed = (self.params.couple_spias or not self.couple) and min_age >= self.params.spias_permitted_from_age
        if not self.params.real_spias or not spias_allowed:
            real_spias_fraction = None
        if not self.params.nominal_spias or not spias_allowed:
            nominal_spias_fraction = None

        # Softmax.
        stocks = exp(stocks_action) if self.params.stocks else 0
        real_bonds = exp(real_bonds_action) if self.params.real_bonds else 0
        nominal_bonds = exp(nominal_bonds_action) if self.params.nominal_bonds else 0
        iid_bonds = exp(iid_bonds_action) if self.params.iid_bonds else 0
        bills = exp(bills_action) if self.params.bills else 0
        total = stocks + real_bonds + nominal_bonds + iid_bonds + bills
        stocks /= total
        real_bonds /= total
        nominal_bonds /= total
        iid_bonds /= total
        bills /= total

        asset_allocation = AssetAllocation(fractional = False)
        if self.params.stocks:
            asset_allocation.aa['stocks'] = stocks
        if self.params.real_bonds:
            asset_allocation.aa['real_bonds'] = real_bonds
        if self.params.nominal_bonds:
            asset_allocation.aa['nominal_bonds'] = nominal_bonds
        if self.params.iid_bonds:
            asset_allocation.aa['iid_bonds'] = iid_bonds
        if self.params.bills:
            asset_allocation.aa['bills'] = bills

        real_bonds_duration = self.params.time_period + \
            (self.params.real_bonds_duration_max - self.params.time_period) * (real_bonds_duration_action + 1) / 2

        nominal_bonds_duration = self.params.time_period + \
            (self.params.nominal_bonds_duration_max - self.params.time_period) * (nominal_bonds_duration_action + 1) / 2

        return (consume_fraction, real_spias_fraction, nominal_spias_fraction, asset_allocation, real_bonds_duration, nominal_bonds_duration)

    def _income_estimate(self):

        lifespan = self.life_expectancy_both[self.episode_length] + self.life_expectancy_one[self.episode_length]
        lifespan = max(lifespan, self.params.time_period)
        return self.gi_sum() + self.p_sum() / lifespan

    def p_plus_income(self):

        return self.p_sum() + self.gi_sum() * self.params.time_period

    def spend(self, consume_fraction, real_spias_fraction = 0, nominal_spias_fraction = 0):

        # Sanity check.
        consume_fraction_period = consume_fraction * self.params.time_period
        assert 0 <= consume_fraction_period <= 1

        p = self.p_plus_income()
        #consume_annual = consume_fraction * p
        consume = consume_fraction_period * p
        p -= consume
        if p < 0:
            assert p / self.p_sum() > -1e-15
            p = 0

        taxes_paid = min(self.taxes_due, p) # Don't allow taxes to consume more than p.
        p -= taxes_paid

        p_taxable = self.p_taxable + (p - self.p_sum())
        p_tax_deferred = self.p_tax_deferred + min(p_taxable, 0)
        # Required Minimum Distributions (RMDs) not considered. Would need separate p_tax_deferred for each spouse.
        p_tax_free = self.p_tax_free + min(p_tax_deferred, 0)
        p_taxable = max(p_taxable, 0)
        p_tax_deferred = max(p_tax_deferred, 0)
        if p_tax_free < 0:
            assert p_tax_free / self.p_sum() > -1e-15
            p_tax_free = 0

        if real_spias_fraction != None:
            real_spias_fraction *= self.params.time_period
        else:
            real_spias_fraction = 0
        if nominal_spias_fraction != None:
            nominal_spias_fraction *= self.params.time_period
        else:
            nominal_spias_fraction = 0
        total = real_spias_fraction + nominal_spias_fraction
        if total > 1:
            real_spias_fraction /= total
            nominal_spias_fraction /= total
        real_spias = real_spias_fraction * p
        nominal_spias = nominal_spias_fraction * p
        real_tax_free_spias = min(real_spias, p_tax_free)
        p_tax_free -= real_tax_free_spias
        real_spias -= real_tax_free_spias
        nominal_tax_free_spias = min(nominal_spias, p_tax_free)
        p_tax_free -= nominal_tax_free_spias
        nominal_spias -= nominal_tax_free_spias
        real_tax_deferred_spias = min(real_spias, p_tax_deferred)
        p_tax_deferred -= real_tax_deferred_spias
        real_taxable_spias = real_spias - real_tax_deferred_spias
        nominal_tax_deferred_spias = min(nominal_spias, p_tax_deferred)
        p_tax_deferred -= nominal_tax_deferred_spias
        nominal_taxable_spias = nominal_spias - nominal_tax_deferred_spias
        p_taxable -= real_taxable_spias + nominal_taxable_spias
        if p_taxable < 0:
            assert p_taxable / self.p_sum() > -1e-15
            p_taxable = 0

        return p_tax_free, p_tax_deferred, p_taxable, consume, taxes_paid, \
            real_tax_free_spias, real_tax_deferred_spias, real_taxable_spias, nominal_tax_free_spias, nominal_tax_deferred_spias, nominal_taxable_spias

    def interpret_spending(self, consume_fraction, asset_allocation, *, real_spias_fraction = 0, nominal_spias_fraction = 0,
        real_bonds_duration = None, nominal_bonds_duration = None):

        p_tax_free, p_tax_deferred, p_taxable, consume, taxes_paid, \
            real_tax_free_spias, real_tax_deferred_spias, real_taxable_spias, nominal_tax_free_spias, nominal_tax_deferred_spias, nominal_taxable_spias = \
            self.spend(consume_fraction, real_spias_fraction, nominal_spias_fraction)

        return {
            'consume': consume / self.params.time_period,
            'asset_allocation': asset_allocation,
            'real_spias_purchase': real_tax_free_spias + real_tax_deferred_spias + real_taxable_spias if self.params.real_spias else None,
            'nominal_spias_purchase': nominal_tax_free_spias + nominal_tax_deferred_spias + nominal_taxable_spias if self.params.real_spias else None,
            'real_bonds_duration': real_bonds_duration,
            'nominal_bonds_duration': nominal_bonds_duration,
        }

    def interpret_action(self, action):

        if action is None:
            decoded_action = None
        else:
            decoded_action = self.decode_action(action)
        policified_action = policy(self, decoded_action)
        consume_fraction, real_spias_fraction, nominal_spias_fraction, asset_allocation, real_bonds_duration, nominal_bonds_duration = policified_action
        return self.interpret_spending(consume_fraction, asset_allocation, real_spias_fraction = real_spias_fraction, nominal_spias_fraction = nominal_spias_fraction,
            real_bonds_duration = real_bonds_duration, nominal_bonds_duration = nominal_bonds_duration)

    def add_spias(self, spia, cpi, tax_free_spias, tax_deferred_spias, taxable_spias):

        age = self.age + 1
        payout_fraction = 1 / (1 + self.params.consume_additional)
        if tax_free_spias > 0:
            self.add_db(self.defined_benefits, age = age, premium = tax_free_spias, inflation_adjustment = cpi, joint = true, \
                payout_fraction = payout_fraction, source_of_funds = 'tax_free')
        if tax_deferred_spias > 0:
            self.add_db(self.defined_benefits, age = age, premium = tax_deferred_spias, inflation_adjustment = cpi, joint = true, \
                payout_fraction = payout_fraction, source_of_funds = 'tax_deferred')
        if taxable_spias > 0:
            exclusion_period = ceil(self.life_expectancy_both[self.episode_length] + self.life_expectancy_one[self.episode_length])
                # Highly imperfect, but total exclusion amount will be correct.
            exlusion_amount = taxable_spias / exclusion_period
            self.add_db(self.defined_benefits, age = age, premium = taxable_spias, inflation_adjustment = cpi, joint = true, \
                payout_fraction = payout_fraction, source_of_funds = 'taxable',
                exclusion_period = exclusion_period, exclusion_amount = exclusion_amount)

    def allocate_aa(self, p_tax_free, p_tax_deferred, p_taxable, asset_allocation):

        p = p_tax_free + p_tax_deferred + p_taxable
        tax_free_remaining = p_tax_free
        taxable_remaining = p_taxable

        tax_efficient_order = ('stocks', 'bills', 'iid_bonds', 'nominal_bonds', 'real_bonds')
        tax_inefficient_order = list(tax_efficient_order)
        tax_inefficient_order.reverse()

        tax_free = AssetAllocation(fractional = False)
        for ac in tax_inefficient_order:
            if ac in asset_allocation.aa:
                alloc = min(p * asset_allocation.aa[ac], tax_free_remaining)
                tax_free.aa[ac] = alloc
                tax_free_remaining = max(tax_free_remaining - alloc, 0)

        taxable = AssetAllocation(fractional = False)
        for ac in tax_efficient_order:
            if ac in asset_allocation.aa:
                alloc = min(p * asset_allocation.aa[ac], taxable_remaining)
                taxable.aa[ac] = alloc
                taxable_remaining = max(taxable_remaining - alloc, 0)

        tax_deferred = AssetAllocation(fractional = False)
        for ac in tax_efficient_order:
            if ac in asset_allocation.aa:
                tax_deferred.aa[ac] = max(p * asset_allocation.aa[ac] - tax_free.aa[ac] - taxable.aa[ac], 0)

        return tax_free, tax_deferred, taxable

    def step(self, action):

        if self.params.reproduce_episode != None:
            self._reproducable_seed(self.params.reproduce_episode, self.episode_length, 1)

        if self.direct_action:
            decoded_action = action
        elif action is None:
            decoded_action = None
        else:
            decoded_action = self.decode_action(action)
        policified_action = policy(self, decoded_action)
        consume_fraction, real_spias_fraction, nominal_spias_fraction, asset_allocation, real_bonds_duration, nominal_bonds_duration = policified_action

        p_tax_free, p_tax_deferred, p_taxable, consume, taxes_paid, \
            real_tax_free_spias, real_tax_deferred_spias, real_taxable_spias, nominal_tax_free_spias, nominal_tax_deferred_spias, nominal_taxable_spias = \
            self.spend(consume_fraction, real_spias_fraction, nominal_spias_fraction)
        consume_rate = consume / self.params.time_period
        real_spias_rate = (real_tax_free_spias + real_tax_deferred_spias + real_taxable_spias) / self.params.time_period
        nominal_spias_rate = (nominal_tax_free_spias + nominal_tax_deferred_spias + nominal_taxable_spias) / self.params.time_period

        if real_spias_rate > 0:
            self.add_spias(self.real_spias, 'cpi', real_tax_free_spias, real_tax_deferred_spias, real_taxable_spias)

        if nominal_spias_rate > 0:
            self.add_spias(self.nominal_spias, 0, nominal_tax_free_spias, nominal_tax_deferred_spias, nominal_taxable_spias)

        tax_free_assets, tax_deferred_assets, taxable_assets = self.allocate_aa(p_tax_free, p_tax_deferred, p_taxable, asset_allocation)

        regular_income = self.gi_sum() + self.p_tax_deferred - p_tax_deferred

        inflation = self.bonds.inflation.inflation()
        self.cpi *= inflation

        p_tax_free = 0
        p_tax_deferred = 0
        p_taxable = 0
        for ac in asset_allocation.aa:
            if ac == 'stocks':
                ret = self.stocks.sample()
                dividend_yield = self.params.dividend_yield_stocks
                qualified_dividends = self.params.qualified_dividends_stocks
            else:
                dividend_yield = self.params.dividend_yield_bonds
                qualified_dividends = self.params.qualified_dividends_bonds
                if ac == 'real_bonds':
                    ret = self.bonds.real.sample(real_bonds_duration)
                elif ac == 'nominal_bonds':
                    ret = self.bonds.nominal.sample(nominal_bonds_duration)
                elif ac == 'iid_bonds':
                    ret = self.iid_bonds.sample()
                elif ac == 'bills':
                    ret = self.bills.sample()
                else:
                    assert False
            p_tax_free += tax_free_assets.aa[ac] * ret
            p_tax_deferred += tax_deferred_assets.aa[ac] * ret
            new_taxable = taxable_assets.aa[ac] * ret
            p_taxable += new_taxable
            taxable_buy_sell = taxable_assets.aa[ac] - self.prev_taxable_assets.aa[ac]
            self.taxes.buy_sell(ac, taxable_buy_sell, new_taxable, ret, dividend_yield, qualified_dividends)
            taxable_assets.aa[ac] *= ret

        self.p_tax_free = p_tax_free
        self.p_tax_deferred = p_tax_deferred
        self.p_taxable = p_taxable

        self.taxes_due += self.taxes.tax(regular_income, not self.couple, self.p_taxable, inflation) - taxes_paid

        def clip(utility):
            reward_annual = min(max(utility, - self.params.reward_clip), self.params.reward_clip)
            if self.params.verbose and reward_annual != utility:
                print('Reward out of range - age, p_sum, consume_fraction, utility:', self.age, self.p_sum(), consume_fraction, utility)
            return reward_annual

        if self.couple:
            utility = self.utility.utility(consume_rate / (1 + self.params.consume_additional))
            self.reward_weight = 2 * self.params.time_period
        else:
            utility = self.utility.utility(consume_rate)
            self.reward_weight = self.alive_single[self.episode_length] * self.params.time_period
        self.reward_value = clip(utility)
        reward = self.reward_weight * self.reward_value

        self.age += self.params.time_period
        self.age2 += self.params.time_period

        couple_became_single = self.couple and self.alive_single[self.episode_length + 1] != None
        if couple_became_single:

            self.life_expectancy_both = [0] * len(self.life_expectancy_both)
            self.life_expectancy_one = self.life_expectancy_single

            for db in self.defined_benefits.values():
                db['spia'] = db['spia_single']
                db['sched'] = db['sched_single']
                db['sched_single'] = None
                db['owner'] = db['owner_single']

        for db in self.defined_benefits.values():
            db['sched'].pop(0)
            try:
                db['sched_single'].pop(0)
            except KeyError:
                pass
            db['spia'].set_age(self.age if db['owner'] == 'self' else self.age2)

        self.episode_utility_sum += utility
        self.episode_length += 1

        self.couple = self.alive_single[self.episode_length] == None

        self._step_bonds()

        observation = self._observe()
        done = self.episode_length >= len(self.alive_single) - 1
        info = {}
        if done:
            info['ce'] = self.utility.inverse(self.episode_utility_sum / self.episode_length)

        self.prev_asset_allocation = asset_allocation
        self.prev_taxable_assets = taxable_assets
        self.prev_real_spias_rate = real_spias_rate
        self.prev_nominal_spias_rate = nominal_spias_rate
        self.prev_consume_rate = consume_rate
        self.prev_reward = reward

        # Variables used by policy decison rules:
        self.prev_ret = ret
        self.prev_inflation = inflation

        return observation, reward, done, info

    def _reproducable_seed(self, episode, episode_length, substep):

        seed(episode * 1000000 + episode_length * 1000 + substep, version = 2)

    def _step_bonds(self):

        if not self.params.static_bonds:

            if self.params.reproduce_episode != None:
                self._reproducable_seed(self.params.reproduce_episode, self.episode_length, 2)

            self.bonds_stepper.step()

    def goto(self, step, real_oup_x, inflation_oup_x, gi_real, gi_nominal, p_tax_free):
        '''Goto a reproducable time step. Useful for benchmarking.'''

        assert self.params.sex2 == None

        self.reset()

        if step > 0:

            self.age += step * self.params.time_period
            self.episode_length += step

            self.bonds.real.oup.next_x = real_oup_x
            assert self.bonds.inflation.inflation_a == self.bonds.inflation.bond_a and self.bonds.inflation.inflation_sigma == self.bonds.inflation.bond_sigma
            self.bonds.inflation.oup.next_x = inflation_oup_x
            self.bonds.inflation.inflation_oup.next_x = inflation_oup_x
            self._step_bonds()

        self.gi_real = gi_real
        self.gi_nominal = gi_nominal
        self.p_tax_free = p_tax_free

        return self._observe()

    def set_reproduce_episode(self, episode):

        self.params.reproduce_episode = episode

    def render(self, mode = 'human'):

        print(self.age, self.p_tax_free, self.p_tax_deferred, self.p_taxable, \
              self.prev_asset_allocation, self.prev_consume_rate, self.prev_real_spias_rate, self.prev_nominal_spias_rate, self.prev_reward)

    def seed(self, seed=None):

        return

    def _observe(self):

        couple = int(self.couple)
        single = int(not self.couple)

        life_expectancy_both = self.life_expectancy_both[self.episode_length]
        life_expectancy_one = self.life_expectancy_one[self.episode_length]
        equivalent_consume_to_wealth = 2 * life_expectancy_both / (1 + self.params.consume_additional) + life_expectancy_one

        income = {'tax_free': 0, 'tax_deferred': 0, 'taxable': 0}
        for key, db in self.defined_benefits.items():
            type_of_funds = key[0]
            real = key[1]
            mwr = self.params.real_spias_mwr if real else self.params.nominal_spias_mwr
            pv = db['spia'].premium(1, mwr = mwr)
            income[type_of_funds] += pv
        for key, value in income.items():
            try:
                income[key] /= equivalent_consume_to_wealth
            except ZeroDivisionError:
                income[key] = float('inf')

        p_basis, cg_carry = self.taxes.observe()
        wealth = {'tax_free': self.p_tax_free + p_basis, 'tax_deferred': self.p_tax_deferred, 'taxable': self.p_taxable - p_basis - self.taxes_due + cg_carry}
        for key, value in wealth.items():
            try:
                wealth[key] /= equivalent_consume_to_wealth
            except ZeroDivisionError:
                wealth[key] = float('inf')

        if self.params.observe_interest_rate:
            real_interest_rate, = self.bonds.real.observe()
        else:
            real_interest_rate = 0

        if self.params.observe_inflation_rate:
            inflation_rate, = self.bonds.inflation.observe()
        else:
            inflation_rate = 0

        observe = (couple, single, life_expectancy_both, life_expectancy_one, income['tax_free'], income['tax_deferred'], income['taxable'],
            wealth['tax_free'], wealth['tax_deferred'], wealth['taxable'], real_interest_rate, inflation_rate)
        return np.array(observe, dtype = 'float32')

    def decode_observation(self, obs):

        couple, single, life_expectancy_both, life_expectancy_one, income_tax_free, income_tax_deferred, income_taxable, \
            wealth_tax_free, wealth_tax_deferred, wealth_taxable, real_interest_rate, inflation_rate = obs.tolist()

        return {
            'couple': couple,
            'single': single,
            'life_expectancy_both': life_expectancy_both,
            'life_expectancy_one': life_expectancy_one,
            'income_tax_free': income_tax_free,
            'income_tax_deferred': income_tax_deferred,
            'income_taxable': income_taxable,
            'wealth_tax_free': wealth_tax_free,
            'wealth_tax_deferred': wealth_tax_deferred,
            'wealth_taxable': wealth_taxable,
            'real_interest_rate': real_interest_rate,
            'inflation_rate': inflation_rate
        }
