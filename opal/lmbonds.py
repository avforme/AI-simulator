#!/usr/bin/python3

# AACalc - Asset Allocation Calculator
# Copyright (C) 2016 Gordon Irlam
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

from os import getenv
from sys import path

path.append('..')

from spia import IncomeAnnuity, LifeTable, YieldCurve

prefix = getenv('OPAL_FILE_PREFIX', 'opal')

with open(prefix + '-lm_bonds-params.py') as f:
    params = eval(f.read())

life_table_params = params['life_table']
life_table2_params = params['life_table2']
yield_curve_params = params['yield_curve']
income_annuity_params = params['income_annuity']

with open(prefix + '-lm_bonds.csv', 'w') as f:

    for year in range(0, params['years']):

        life_table = LifeTable(**life_table_params)
        life_table2 = LifeTable(**life_table2_params) if life_table2_params != None else None

        yield_curve_real = YieldCurve(**yield_curve_params)
        yield_curve_zero = YieldCurve(**dict(yield_curve_params, interest_rate = 'fixed'))

        date_str = str(params['now_year'] + year) + '-01-01'
        income_annuity = IncomeAnnuity(yield_curve_real, life_table1 = life_table, life_table2 = life_table2, date_str = date_str, **income_annuity_params)
        lm_bonds_ret = income_annuity.annual_return
        lm_bonds_duration = income_annuity.duration
        f.write("%d,%f,%f\n" % (year, lm_bonds_ret, lm_bonds_duration))

        life_table_params['age'] += 1
        if life_table2_params:
            life_table2_params['age'] += 1

        income_annuity_params['payout_delay'] = max(0, income_annuity_params['payout_delay'] - 12)
