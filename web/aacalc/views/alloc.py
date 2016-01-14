# AACalc - Asset Allocation Calculator
# Copyright (C) 2009, 2011-2016 Gordon Irlam
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from datetime import datetime, timedelta
from decimal import Decimal
from math import ceil, exp, isnan, log, sqrt
from os import umask
from tempfile import mkdtemp

from django.forms.forms import NON_FIELD_ERRORS
from django.forms.util import ErrorList
from django.shortcuts import render
from numpy import array
from numpy.linalg import inv, LinAlgError
from scipy.stats import lognorm, norm
from subprocess import check_call

from aacalc.forms import AllocAaForm, AllocNumberForm
from aacalc.spia import LifeTable, Scenario, YieldCurve
from settings import ROOT, STATIC_ROOT, STATIC_URL

class Alloc:

    class IdenticalCovarError(Exception):
        pass

    def default_alloc_params(self):

        return {
            'sex': 'male',
            'age': 50,
            'le_add': 6,
            'sex2': 'none',
            'age2': '',
            'le_add2': 6,
            'date': (datetime.utcnow() + timedelta(hours = -24)).date().isoformat(),  # Yesterday's quotes are retrieved at midnight.

            'db' : ({
                'description': 'Social Security',
                'who': 'self',
                'age': 65,
                'amount': 15000,
                'inflation_indexed': True,
                'period_certain': 0,
                'joint_type': 'survivor',
                'joint_payout_pct': 0,
            }, {
                'description': 'Pension',
                'who': 'self',
                'age': 65,
                'amount': 0,
                'inflation_indexed': True,
                'period_certain': 0,
                'joint_type': 'survivor',
                'joint_payout_pct': 0,
            }, {
                'description': 'Income annuity',
                'who': 'self',
                'age': 65,
                'amount': 0,
                'inflation_indexed': True,
                'period_certain': 0,
                'joint_type': 'contingent',
                'joint_payout_pct': 70,
            }, {
                'description': 'Income annuity',
                'who': 'self',
                'age': 65,
                'amount': 0,
                'inflation_indexed': False,
                'period_certain': 0,
                'joint_type': 'contingent',
                'joint_payout_pct': 70,
            }, {
                'description': 'Social Security',
                'who': 'spouse',
                'age': 65,
                'amount': 0,
                'inflation_indexed': True,
                'period_certain': 0,
                'joint_type': 'survivor',
                'joint_payout_pct': 0,
            }, {
                'description': 'Pension',
                'who': 'spouse',
                'age': 65,
                'amount': 0,
                'inflation_indexed': True,
                'period_certain': 0,
                'joint_type': 'survivor',
                'joint_payout_pct': 0,
            }, {
                'description': 'Income annuity',
                'who': 'spouse',
                'age': 65,
                'amount': 0,
                'inflation_indexed': True,
                'period_certain': 0,
                'joint_type': 'contingent',
                'joint_payout_pct': 70,
            }, {
                'description': 'Income annuity',
                'who': 'spouse',
                'age': 65,
                'amount': 0,
                'inflation_indexed': False,
                'period_certain': 0,
                'joint_type': 'contingent',
                'joint_payout_pct': 70,
            }),
            'p_traditional_iras': 0,
            'tax_rate_pct': 30,
            'p_roth_iras': 0,
            'p': 0,
            'contribution': 2000,
            'contribution_growth_pct': 7,
            'contribution_vol_pct': 10,
            'equity_contribution_corr_pct': 0,
            'bonds_contribution_corr_pct': 0,

            'retirement_age': 65,
            'joint_income_pct': 70,
            'desired_income': 40000,
            'purchase_income_annuity': True,

            'equity_ret_pct': Decimal('7.2'),
            'equity_vol_pct': Decimal('17.0'),
            'bonds_ret_pct': Decimal('0.8'),
            'bonds_vol_pct': Decimal('4.1'),
            'equity_bonds_corr_pct': Decimal('7.2'),
            'equity_se_pct': Decimal('1.7'),
            'confidence_pct': 80,
            'expense_pct': Decimal('0.1'),

            'gamma': Decimal('4.0'),
        }

    def geomean(self, mean, vol):
        # Convert mean and vol to lognormal distribution mu and sigma parameters.
        mu = log(mean ** 2 / sqrt(vol ** 2 + mean ** 2))
        sigma = sqrt(log(vol ** 2 / mean ** 2 + 1))
        # Compute the middle value.
        geomean = lognorm.ppf(0.5, sigma, scale=exp(mu))
        geomean = float(geomean) # De-numpyfy.
        if isnan(geomean):
            # vol == 0.
            geomean = mean
        return geomean

    def solve_merton(self, gamma, sigma_matrix, alpha, r):
        try:
            w = inv(sigma_matrix).dot(array(alpha) - r) / gamma
        except LinAlgError:
            raise self.IdenticalCovarError
        return tuple(float(wi) for wi in w) # De-numpyfy.

    def stochastic_schedule(self, mean, years = None):

        def sched(y):
            if years == None or y < years:
                return mean ** y
            else:
                return 0

        return sched

    def npv_contrib(self, ret):
        payout_delay = 0
        schedule = self.stochastic_schedule(1 + ret, self.pre_retirement_years)
        scenario = Scenario(self.yield_curve_real, payout_delay, None, None, 0, self.life_table_120, life_table2 = self.life_table_120, \
            joint_payout_fraction = 1, joint_contingent = True, period_certain = self.period_certain, \
            frequency = 1, cpi_adjust = 'all', schedule = schedule)
            # Table used is irrelevant. Choose for speed.
        return self.contribution * scenario.price()

    def value_table(self, taxable):

        nv_db = 0
        results = {}
        display = {}
        display['db'] = []

        for db in self.db:

            amount = float(db['amount'])

            if amount == 0:
                continue

            yield_curve = self.yield_curve_real if db['inflation_indexed'] else self.yield_curve_nominal

            if db['who'] == 'self':
                starting_age = self.age
                lt1 = self.life_table_add
                lt2 = self.life_table2_add
            else:
                starting_age = self.age2
                lt1 = self.life_table2_add
                lt2 = self.life_table_add

            delay = float(db['age']) - starting_age
            positive_delay = max(0, delay)
            negative_delay = min(0, delay)
            payout_delay = positive_delay * 12
            period_certain = max(0, self.period_certain - positive_delay, float(db['period_certain']) + negative_delay)
            joint_payout_fraction = float(db['joint_payout_pct']) / 100
            joint_contingent = (db['joint_type'] == 'contingent')

            scenario = Scenario(yield_curve, payout_delay, None, None, 0, lt1, life_table2 = lt2, \
                joint_payout_fraction = joint_payout_fraction, joint_contingent = joint_contingent, \
                period_certain = period_certain, frequency = self.frequency, cpi_adjust = self.cpi_adjust)
            price = scenario.price() * amount
            nv_db += price

            display['db'].append({
                'description': db['description'],
                'who': db['who'],
                'nv': '{:,.0f}'.format(price),
            })

        nv_contributions = self.npv_contrib(self.contribution_growth)

        nv_traditional = self.traditional * (1 - self.tax_rate)
        nv_investments = nv_traditional + self.npv_roth + taxable
        nv = nv_db + nv_investments + nv_contributions

        results['nv_contributions'] = nv_contributions
        results['nv_db'] = nv_db
        results['nv'] = nv

        display['nv_db'] = '{:,.0f}'.format(nv_db)
        display['nv_traditional'] = '{:,.0f}'.format(nv_traditional)
        display['nv_roth'] = '{:,.0f}'.format(self.npv_roth)
        display['nv_taxable'] = '{:,.0f}'.format(taxable)
        display['nv_investments'] = '{:,.0f}'.format(nv_investments)
        display['nv_contributions'] = '{:,.0f}'.format(nv_contributions)
        display['nv'] = '{:,.0f}'.format(nv)

        return results, display

    def consume_factor(self, alloc_contrib, alloc_equity, alloc_bonds, alloc_lm_bonds, alloc_db, \
            future_growth, equity_ret, bonds_ret, lm_bonds_ret, \
            equity_vol, bonds_vol, cov_ec2, cov_bc2, cov_eb2):

        total_ret = alloc_contrib * future_growth + alloc_equity * equity_ret + alloc_bonds * bonds_ret + \
            alloc_lm_bonds * lm_bonds_ret + alloc_db * lm_bonds_ret
        total_var = alloc_contrib ** 2 * self.contribution_vol ** 2 + \
            alloc_equity ** 2 * equity_vol ** 2 + \
            alloc_bonds ** 2 * bonds_vol ** 2 + \
            2 * alloc_contrib * alloc_equity * cov_ec2 + \
            2 * alloc_contrib * alloc_bonds * cov_bc2 + \
            2 * alloc_equity * alloc_bonds * cov_eb2
        total_vol = sqrt(total_var)

        # We should use total_var, total_vol, and gamma to compute the
        # annual consumption amount.  Merton's Continuous Time Finance
        # provides solutions for a single risky asset with a finite
        # time horizon, and many asset with a infinite time horizon,
        # but not many assets with a finite time horizon. And even if
        # such a solution existed we would also need to factor in
        # pre-retirement years. Instead we compute the withdrawal
        # amount for a fixed compounding total portfolio.
        life_table_partial = LifeTable(self.table, self.sex, self.age, le_add = (1 - alloc_db) * self.le_add, date_str = self.date_str)
        if self.sex2 != 'none':
            life_table2_partial = LifeTable(self.table, self.sex2, self.age2, le_add = (1 - alloc_db) * self.le_add2, date_str = self.date_str)
        else:
            life_table2_partial = None
        periodic_ret = self.geomean(total_ret, total_vol)
        schedule = self.stochastic_schedule(1 / (1.0 + periodic_ret))
        scenario = Scenario(self.yield_curve_zero, self.payout_delay, None, None, 0, life_table_partial, life_table2 = life_table2_partial, \
            joint_payout_fraction = self.joint_payout_fraction, joint_contingent = True, \
            period_certain = 0, frequency = self.frequency, cpi_adjust = self.cpi_adjust, schedule = schedule)
        c_factor = 1.0 / scenario.price()

        return c_factor, total_ret, total_vol

    def calc_scenario(self, mode, description, factor, data, results):

        scenario = Scenario(self.yield_curve_real, self.payout_delay, None, None, 0, self.life_table_add, life_table2 = self.life_table2_add, \
            joint_payout_fraction = self.joint_payout_fraction, joint_contingent = True, \
            period_certain = 0, frequency = self.frequency, cpi_adjust = self.cpi_adjust)
        scenario.price()
        retirement_le = scenario.total_payout
        lm_bonds_ret = scenario.annual_return
        lm_bonds_duration = scenario.duration

        expense = float(data['expense_pct']) / 100
        equity_ret = float(data['equity_ret_pct']) / 100 - expense
        equity_ret += factor * float(data['equity_se_pct']) / 100
        bonds_ret = float(data['bonds_ret_pct']) / 100 - expense
        gamma = float(data['gamma'])
        equity_vol = float(data['equity_vol_pct']) / 100
        bonds_vol = float(data['bonds_vol_pct']) / 100

        equity_gm = self.geomean(1 + equity_ret, equity_vol) - 1
        bonds_gm = self.geomean(1 + bonds_ret, bonds_vol) - 1

        equity_bonds_corr = float(data['equity_bonds_corr_pct']) / 100
        cov_ec2 = equity_vol * self.contribution_vol * self.equity_contribution_corr ** 2
        cov_bc2 = bonds_vol * self.contribution_vol * self.bonds_contribution_corr ** 2
        cov_eb2 = equity_vol * bonds_vol * equity_bonds_corr ** 2
        stocks_index = 0
        bonds_index = 1
        contrib_index = 2
        risk_free_index = 3

        if mode == 'aa':
            lo = -0.5
            hi = 0.5
        else:
            lo = hi = 0
        for _ in range(50):
            future_growth_try = (lo + hi) / 2.0
            sigma_matrix = (
                (equity_vol ** 2, cov_eb2, cov_ec2),
                (cov_eb2, bonds_vol ** 2, cov_bc2),
                (cov_ec2, cov_bc2, self.contribution_vol ** 2)
            )
            alpha = (equity_ret, bonds_ret, future_growth_try)
            w = list(self.solve_merton(gamma, sigma_matrix, alpha, lm_bonds_ret))
            w.append(1 - sum(w))
            discounted_contrib = self.npv_contrib((1 + self.contribution_growth) / (1 + future_growth_try) - 1)
            npv_discounted = results['nv'] - results['nv_contributions'] + discounted_contrib
            try:
                wc_discounted = discounted_contrib / npv_discounted
            except ZeroDivisionError:
                wc_discounted = 0
            if hi - lo < 0.000001:
                break
            if wc_discounted > w[contrib_index]:
                lo = future_growth_try
            else:
                hi = future_growth_try
        try:
            w_prime = list(wi * npv_discounted / results['nv'] for wi in w)
        except ZeroDivisionError:
            w_prime = list(0 for _ in w)
        w_prime[contrib_index] = 0
        w_prime[contrib_index] = 1 - sum(w_prime)
        w_prime = list(max(0, wi) for wi in w_prime)
        w_prime[risk_free_index] = 0
        w_prime[risk_free_index] = 1 - sum(w_prime)

        if data['purchase_income_annuity']:
            annuitize_equity = min(max(0, (self.min_age - 70.0) / (90 - 70)), 1)
            # Don't have a good handle on when to annuitize regular
            # bonds.  Results are from earlier work in which bonds
            # returned 3.1 +/- 11.9% based on historical data.  These
            # returns are unlikely to be repeated in the forseeable
            # future.
            annuitize_bonds = min(max(0, (self.min_age - 30.0) / (60 - 30)), 1)
            # Empirically LM bond allocations seem to be more or less
            # fixed.  Largely invariant under changes in gamma,
            # mortality, and stock return.  They do howver increase if
            # stock volatility increases, MWR decreases, or the real
            # yield curve increases (unexplained).  This suggests they
            # play a buffering role. We would annuitize everything,
            # except we need some free fixed assets in order to be
            # able to rebalance.  The sensitivity isn't that great
            # what would be 18% becomes 24%, 23%, and 24% and 30% for
            # reasonable perturbations of the above values. We use 20%
            # as a rule of thumb value.
            alloc_lm_bonds = max(0, min(w_prime[risk_free_index], 0.20 * (1 - min(max(0, (self.min_age - 20.0) / (70 - 20)), 1))))
            try:
                annuitize_lm_bonds = 1 - alloc_lm_bonds / w_prime[risk_free_index]
            except ZeroDivisionError:
                annuitize_lm_bonds = 0
        else:
            annuitize_equity = 0
            annuitize_bonds = 0
            alloc_lm_bonds = min(max(0, w_prime[risk_free_index]), 1)
            annuitize_lm_bonds = 0
        alloc_equity = min(max(0, w_prime[stocks_index] * (1 - annuitize_equity)), 1)
        alloc_bonds = min(max(0, w_prime[bonds_index] * (1 - annuitize_bonds)), 1)
        try:
            alloc_contrib = results['nv_contributions'] / results['nv']
        except ZeroDivisionError:
            alloc_contrib = 1
        alloc_db = 1 - alloc_equity - alloc_bonds - alloc_contrib - alloc_lm_bonds
        try:
            alloc_existing_db = results['nv_db'] / results['nv']
        except ZeroDivisionError:
            alloc_existing_db = 0
        shortfall = alloc_db - alloc_existing_db
        if data['purchase_income_annuity']:
            shortfall = min(0, shortfall)
        alloc_db -= shortfall
        alloc_db = max(0, alloc_db) # Eliminate negative values from fp rounding errors.
        alloc_lm_bonds += shortfall
        if alloc_lm_bonds < 0:
            surplus = alloc_lm_bonds
        else:
            surplus = max(alloc_lm_bonds - 1, 0)
        alloc_lm_bonds -= surplus
        alloc_bonds += surplus
        if alloc_bonds < 0:
            surplus = alloc_bonds
        else:
            surplus = max(alloc_bonds - 1, 0)
        alloc_bonds -= surplus
        alloc_equity += surplus
        alloc_new_db = max(0, alloc_db - alloc_existing_db) # Eliminate negative values from fp rounding errors.

        c_factor, total_ret, total_vol = self.consume_factor(alloc_contrib, alloc_equity, alloc_bonds, alloc_lm_bonds, alloc_db, \
            future_growth_try, equity_ret, bonds_ret, lm_bonds_ret, \
            equity_vol, bonds_vol, cov_ec2, cov_bc2, cov_eb2)
        consume = c_factor * results['nv']

        if consume > self.desired_income:
            ratio = self.desired_income / consume
            alloc_bonds *= ratio
            alloc_lm_bonds *= ratio
            alloc_new_db = max(0, alloc_db * ratio - alloc_existing_db)
            alloc_equity = 1 - (alloc_contrib + alloc_bonds + alloc_lm_bonds + alloc_existing_db + alloc_new_db)

        c_factor, total_ret, total_vol = self.consume_factor(alloc_contrib, alloc_equity, alloc_bonds, alloc_lm_bonds, alloc_db, \
            future_growth_try, equity_ret, bonds_ret, lm_bonds_ret, \
            equity_vol, bonds_vol, cov_ec2, cov_bc2, cov_eb2)
        consume = c_factor * results['nv']

        alloc_equity = max(0, alloc_equity) # Eliminate negative values from fp rounding errors.

        try:
            aa_equity = alloc_equity / (alloc_equity + alloc_bonds + alloc_lm_bonds)
        except ZeroDivisionError:
            aa_equity = 1
        aa_bonds = 1 - aa_equity

        purchase_income_annuity = alloc_new_db * results['nv']

        result = {
            'description': description,
            'lm_bonds_ret_pct': '{:.1f}'.format(lm_bonds_ret * 100),
            'lm_bonds_duration': '{:.1f}'.format(lm_bonds_duration),
            'retirement_life_expectancy': '{:.1f}'.format(retirement_le),
            'consume': '{:,.0f}'.format(consume),
            'equity_am_pct':'{:.1f}'.format(equity_ret * 100),
            'bonds_am_pct':'{:.1f}'.format(bonds_ret * 100),
            'equity_gm_pct':'{:.1f}'.format(equity_gm * 100),
            'bonds_gm_pct':'{:.1f}'.format(bonds_gm * 100),
            'future_growth_try_pct': '{:.1f}'.format(future_growth_try * 100),
            'w' : [{
                'name' : 'Discounted future contributions',
                'alloc': '{:.0f}'.format(w[contrib_index] * 100),
            }, {
                'name': 'Stocks',
                'alloc': '{:.0f}'.format(w[stocks_index] * 100),
            }, {
                'name': 'Regular bonds',
                'alloc': '{:.0f}'.format(w[bonds_index] * 100),
            }, {
                'name': 'Liability matching bonds and defined benefits',
                'alloc': '{:.0f}'.format(w[risk_free_index] * 100),
            }],
            'discounted_contrib': '{:,.0f}'.format(discounted_contrib),
            'wc_discounted':  '{:.0f}'.format(wc_discounted * 100),
            'w_prime' : [{
                'name' : 'Future contributions',
                'alloc': '{:.0f}'.format(w_prime[contrib_index] * 100),
            }, {
                'name': 'Stocks',
                'alloc': '{:.0f}'.format(w_prime[stocks_index] * 100),
            }, {
                'name': 'Regular bonds',
                'alloc': '{:.0f}'.format(w_prime[bonds_index] * 100),
            }, {
                'name': 'Liability matching bonds and defined benefits',
                'alloc': '{:.0f}'.format(w_prime[risk_free_index] * 100),
            }],
            'annuitize_equity_pct': '{:.0f}'.format(annuitize_equity * 100),
            'annuitize_bonds_pct': '{:.0f}'.format(annuitize_bonds * 100),
            'annuitize_lm_bonds_pct': '{:.0f}'.format(annuitize_lm_bonds * 100),
            'alloc_equity_pct': '{:.0f}'.format(alloc_equity * 100),
            'alloc_bonds_pct': '{:.0f}'.format(alloc_bonds * 100),
            'alloc_lm_bonds_pct': '{:.0f}'.format(alloc_lm_bonds * 100),
            'alloc_contributions_pct': '{:.0f}'.format(alloc_contrib * 100),
            'alloc_existing_db_pct': '{:.0f}'.format(alloc_existing_db * 100),
            'alloc_new_db_pct': '{:.0f}'.format(alloc_new_db * 100),
            'purchase_income_annuity': '{:,.0f}'.format(purchase_income_annuity),
            'aa_equity_pct': '{:.0f}'.format(aa_equity * 100),
            'aa_bonds_pct': '{:.0f}'.format(aa_bonds * 100),
            'equity_ret_pct': '{:.1f}'.format(equity_ret * 100),
            'bonds_ret_pct': '{:.1f}'.format(bonds_ret * 100),
            'lm_bonds_ret_pct': '{:.1f}'.format(lm_bonds_ret * 100),
            'total_ret_pct': '{:.1f}'.format(total_ret * 100),
            'total_vol_pct': '{:.1f}'.format(total_vol * 100),
            'consume_value': consume,
            'alloc_equity': alloc_equity,
            'alloc_bonds': alloc_bonds,
            'alloc_lm_bonds': alloc_lm_bonds,
            'alloc_contributions': alloc_contrib,
            'alloc_existing_db': alloc_existing_db,
            'alloc_new_db': alloc_new_db,
            'aa_equity': aa_equity,
            'aa_bonds': aa_bonds,
        }

        if mode == 'number':
            result['w'].pop(0)
            result['w_prime'].pop(0)

        return result

    def calc(self, mode, description, factor, data, results):

        if mode == 'aa':

            return self.calc_scenario(mode, description, factor, data, results)

        else:

            results = dict(results)
            nv = results['nv']
            max_portfolio = self.desired_income * (120 - self.min_age - self.pre_retirement_years)
            low = 0
            high = max_portfolio
            for _ in range(50):
                mid = (low + high) / 2.0
                # Hack the table rather than recompute for speed.
                results['nv'] = nv + mid
                calc_scenario = self.calc_scenario(mode, description, factor, data, results)
                if high - low < 0.00001 * max_portfolio:
                    break
                if calc_scenario['consume_value'] < self.desired_income:
                    low = mid
                else:
                    high = mid
            _, npv_display = self.value_table(mid) # Recompute.
            calc_scenario['npv_display'] = npv_display

            return calc_scenario

    def compute_results(self, data, mode):

        results = {}

        self.date_str = data['date']
        self.yield_curve_real = YieldCurve('real', self.date_str)
        self.yield_curve_nominal = YieldCurve('nominal', self.date_str)
        self.yield_curve_zero = YieldCurve('fixed', self.date_str)

        if self.yield_curve_real.yield_curve_date == self.yield_curve_nominal.yield_curve_date:
            results['yield_curve_date'] = self.yield_curve_real.yield_curve_date;
        else:
            results['yield_curve_date'] = self.yield_curve_real.yield_curve_date + ' real, ' + \
                self.yield_curve_nominal.yield_curve_date + ' nominal';

        self.table = 'ssa-cohort'

        self.life_table_120 = LifeTable('death_120', 'male', 0)

        self.sex = data['sex']
        self.age = float(data['age'])
        self.le_add = float(data['le_add'])
        self.life_table_add = LifeTable(self.table, self.sex, self.age, le_add = self.le_add, date_str = self.date_str)

        self.sex2 = data['sex2']
        if self.sex2 == 'none':
            self.life_table2 = None
            self.life_table2_add = None
            self.min_age = self.age
        else:
            self.age2 = float(data['age2']);
            self.le_add2 = float(data['le_add2'])
            self.life_table2_add = LifeTable(self.table, self.sex2, self.age2, le_add = self.le_add2, date_str = self.date_str)
            self.min_age = min(self.age, self.age2)

        self.db = data['db']
        if mode == 'aa':
            self.traditional = float(data['p_traditional_iras'])
            self.tax_rate = float(data['tax_rate_pct']) / 100
            self.npv_roth = float(data['p_roth_iras'])
            self.npv_taxable = float(data['p'])
            self.contribution = float(data['contribution'])
            self.contribution_growth = float(data['contribution_growth_pct']) / 100
            self.contribution_vol = float(data['contribution_vol_pct']) / 100
            self.equity_contribution_corr = float(data['equity_contribution_corr_pct']) / 100
            self.bonds_contribution_corr = float(data['bonds_contribution_corr_pct']) / 100
        else:
            self.traditional = 0
            self.tax_rate = 0
            self.npv_roth = 0
            self.npv_taxable = 0
            self.contribution = 0
            self.contribution_growth = 0
            self.contribution_vol = 0.1 # Prevent covariance matrix inverse failing.
            self.equity_contribution_corr = 0
            self.bonds_contribution_corr = 0
        self.retirement_age = float(data['retirement_age'])
        self.pre_retirement_years = max(0, self.retirement_age - self.age)
        self.payout_delay = self.pre_retirement_years * 12
        self.joint_payout_fraction = float(data['joint_income_pct']) / 100
        self.desired_income = float(data['desired_income'])

        results['pre_retirement_years'] = '{:.1f}'.format(self.pre_retirement_years)

        self.period_certain = self.pre_retirement_years
            # For planning purposes when computing the npv of defined benefits
            # and contributions we need to assume we will reach retirement.

        self.frequency = 12 # Monthly. Makes accurate, doesn't run significantly slower.
        self.cpi_adjust = 'calendar'

        npv_results, npv_display = self.value_table(self.npv_taxable)
        results['db'] = []
        for db in npv_display['db']:
            results['db'].append({'present': db})
        #for i, db in enumerate(future_display['db']):
        #    results['db'][i]['future'] = db

        factor = norm.ppf(0.5 + float(data['confidence_pct']) / 100 / 2)
        factor = float(factor) # De-numpyfy.
        results['calc'] = (
            self.calc(mode, 'Baseline estimate', 0, data, npv_results),
            self.calc(mode, 'Low returns estimate', - factor, data, npv_results),
            self.calc(mode, 'High returns estimate', factor, data, npv_results),
        )

        if mode == 'number':
            npv_display = results['calc'][0]['npv_display'] # Use baseline scenario for common calculations display.

        results['present'] = npv_display

        return results

    def plot(self, mode, result):
        umask(0077)
        parent = STATIC_ROOT + 'results'
        dirname = mkdtemp(prefix='aa-', dir=parent)
        f = open(dirname + '/alloc.csv', 'w')
        f.write('''class,allocation
stocks,%(alloc_equity)f
regular bonds,%(alloc_bonds)f
LM bonds,%(alloc_lm_bonds)f
defined benefits,%(alloc_existing_db)f
new annuities,%(alloc_new_db)f
''' % result)
        if mode == 'aa':
            f.write('''future contribs,%(alloc_contributions)f
''' % result)
        f.close()
        f = open(dirname + '/aa.csv', 'w')
        f.write('''asset class,allocation
stocks,%(aa_equity)f
bonds,%(aa_bonds)f
''' % result)
        f.close()
        cmd = ROOT + '/web/plot.R'
        prefix = dirname + '/'
        check_call((cmd, '--args', prefix))
        return dirname

    def alloc_init(self, data, mode):

        return AllocAaForm(data) if mode == 'aa' else AllocNumberForm(data)

    def alloc(self, request, mode):

        errors_present = False

        results = {}

        if request.method == 'POST':

            alloc_form = self.alloc_init(request.POST, mode)

            if alloc_form.is_valid():

                try:

                    data = alloc_form.cleaned_data
                    results = self.compute_results(data, mode)
                    dirname = self.plot(mode, results['calc'][0])
                    results['dirurl'] = dirname.replace(STATIC_ROOT, STATIC_URL)

                except LifeTable.UnableToAdjust:

                    errors = alloc_form._errors.setdefault('le_add2', ErrorList())  # Simplified in Django 1.7.
                    errors.append('Unable to adjust life table.')

                    errors_present = True

                except YieldCurve.NoData:

                    errors = alloc_form._errors.setdefault('date', ErrorList())  # Simplified in Django 1.7.
                    errors.append('No interest rate data available for the specified date.')

                    errors_present = True

                except self.IdenticalCovarError:

                    errors = alloc_form._errors.setdefault(NON_FIELD_ERRORS, ErrorList())  # Simplified in Django 1.7.
                    errors.append('Two or more rows of covariance matrix appear equal under scaling. This means asset allocation has no unique solution.')

                    errors_present = True

            else:

                errors_present = True

        else:

            alloc_form = self.alloc_init(self.default_alloc_params(), mode)

        return render(request, 'alloc.html', {
            'errors_present': errors_present,
            'mode': mode,
            'alloc_form': alloc_form,
            'results': results,
        })

def alloc(request, mode):
    return Alloc().alloc(request, mode)
