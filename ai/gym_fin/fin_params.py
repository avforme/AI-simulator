# AIPlanner - Deep Learning Financial Planner
# Copyright (C) 2021 Gordon Irlam
#
# All rights reserved. This program may not be used, copied, modified,
# or redistributed without permission.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the
# implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
# PURPOSE.

import cython

@cython.cclass
class FinParams:

    # This entire file would be just:
    #
    #     class FinParams:
    #
    #         def __init__(self, params):
    #
    #            self.__dict__.update(params)
    #
    # Except lookups would be slow in Cython.

    def __init__(self, params):

        self.action_space_unbounded = params['action_space_unbounded']
        self.age_end = params['age_end']
        self.age_retirement_high = params['age_retirement_high']
        self.age_retirement_low = params['age_retirement_low']
        self.age_start = params['age_start']
        self.age_start2_high = params['age_start2_high']
        self.age_start2_low = params['age_start2_low']
        self.algorithm = params['algorithm']
        self.annuitization_policy = params['annuitization_policy']
        self.annuitization_policy_age = params['annuitization_policy_age']
        self.annuitization_policy_annuitization_fraction = params['annuitization_policy_annuitization_fraction']
        self.asset_allocation_annuitized_policy = params['asset_allocation_annuitized_policy']
        self.asset_allocation_glide_path = params['asset_allocation_glide_path']
        self.asset_allocation_policy = params['asset_allocation_policy']
        self.bonds_date = params['bonds_date']
        self.bonds_date_start = params['bonds_date_start']
        self.bonds_standard_error = params['bonds_standard_error']
        self.consume_action_scale_back = params['consume_action_scale_back']
        self.consume_additional = params['consume_additional']
        self.consume_ceiling = params['consume_ceiling']
        self.consume_charitable = params['consume_charitable']
        self.consume_charitable_discount_rate = params['consume_charitable_discount_rate']
        self.consume_charitable_gamma = params['consume_charitable_gamma']
        self.consume_charitable_tax_deductability = params['consume_charitable_tax_deductability']
        self.consume_charitable_utility_factor = params['consume_charitable_utility_factor']
        self.consume_floor = params['consume_floor']
        self.consume_initial = params['consume_initial']
        self.consume_policy = params['consume_policy']
        self.consume_policy_extended_rmd_table = params['consume_policy_extended_rmd_table']
        self.consume_policy_fraction = params['consume_policy_fraction']
        self.consume_policy_fraction_max = params['consume_policy_fraction_max']
        self.consume_policy_life_expectancy = params['consume_policy_life_expectancy']
        self.consume_policy_return = params['consume_policy_return']
        self.consume_preretirement = params['consume_preretirement']
        self.consume_preretirement_income_ratio_high = params['consume_preretirement_income_ratio_high']
        self.consume_preretirement_income_ratio_low = params['consume_preretirement_income_ratio_low']
        self.corporate_nominal_spread = params['corporate_nominal_spread']
        self.couple_death_concordant = params['couple_death_concordant']
        self.couple_death_preretirement_consume = params['couple_death_preretirement_consume']
        self.couple_hide = params['couple_hide']
        self.couple_probability = params['couple_probability']
        self.couple_spias = params['couple_spias']
        self.credit_rate = params['credit_rate']
        self.debug_dummy_float = params['debug_dummy_float']
        self.display_returns = params['display_returns']
        self.dividend_yield_bonds = params['dividend_yield_bonds']
        self.dividend_yield_stocks = params['dividend_yield_stocks']
        self.fixed_nominal_bonds_rate = params['fixed_nominal_bonds_rate']
        self.fixed_real_bonds_rate = params['fixed_real_bonds_rate']
        self.gamma_high = params['gamma_high']
        self.gamma_low = params['gamma_low']
        self.gi_fraction_high = params['gi_fraction_high']
        self.gi_fraction_low = params['gi_fraction_low']
        self.guaranteed_income = params['guaranteed_income']
        self.guaranteed_income_additional = params['guaranteed_income_additional']
        self.have_401k2_high = params['have_401k2_high']
        self.have_401k2_low = params['have_401k2_low']
        self.have_401k_high = params['have_401k_high']
        self.have_401k_low = params['have_401k_low']
        self.iid_bonds = params['iid_bonds']
        self.iid_bonds_duration = params['iid_bonds_duration']
        self.iid_bonds_duration_action_force = params['iid_bonds_duration_action_force']
        self.iid_bonds_return = params['iid_bonds_return']
        self.iid_bonds_type = params['iid_bonds_type']
        self.iid_bonds_volatility = params['iid_bonds_volatility']
        self.income_aggregate = params['income_aggregate']
        self.income_preretirement2_high = params['income_preretirement2_high']
        self.income_preretirement2_low = params['income_preretirement2_low']
        self.income_preretirement_age_end = params['income_preretirement_age_end']
        self.income_preretirement_age_end2 = params['income_preretirement_age_end2']
        self.income_preretirement_concordant = params['income_preretirement_concordant']
        self.income_preretirement_high = params['income_preretirement_high']
        self.income_preretirement_low = params['income_preretirement_low']
        self.income_preretirement_mu = params['income_preretirement_mu']
        self.income_preretirement_mu2 = params['income_preretirement_mu2']
        self.income_preretirement_sigma = params['income_preretirement_sigma']
        self.income_preretirement_sigma2 = params['income_preretirement_sigma2']
        self.income_preretirement_taxable = params['income_preretirement_taxable']
        self.inflation_adjust = params['inflation_adjust']
        self.inflation_short_rate_type = params['inflation_short_rate_type']
        self.inflation_short_rate_value = params['inflation_short_rate_value']
        self.inflation_standard_error = params['inflation_standard_error']
        self.life_expectancy_additional2_high = params['life_expectancy_additional2_high']
        self.life_expectancy_additional2_low = params['life_expectancy_additional2_low']
        self.life_expectancy_additional_high = params['life_expectancy_additional_high']
        self.life_expectancy_additional_low = params['life_expectancy_additional_low']
        self.life_table = params['life_table']
        self.life_table_date = params['life_table_date']
        self.life_table_interpolate_q = params['life_table_interpolate_q']
        self.life_table_spia = params['life_table_spia']
        self.name = params['name']
        self.nominal_bonds = params['nominal_bonds']
        self.nominal_bonds_adjust = params['nominal_bonds_adjust']
        self.nominal_bonds_duration = params['nominal_bonds_duration']
        self.nominal_bonds_duration_action_force = params['nominal_bonds_duration_action_force']
        self.nominal_bonds_duration_max = params['nominal_bonds_duration_max']
        self.nominal_spias = params['nominal_spias']
        self.nominal_spias_adjust = params['nominal_spias_adjust']
        self.nominal_spias_mwr = params['nominal_spias_mwr']
        self.observation_space_clip = params['observation_space_clip']
        self.observation_space_ignores_range = params['observation_space_ignores_range']
        self.observation_space_warn = params['observation_space_warn']
        self.observe_interest_rate = params['observe_interest_rate']
        self.observe_stocks_price = params['observe_stocks_price']
        self.observe_stocks_volatility = params['observe_stocks_volatility']
        self.p_tax_deferred_high = params['p_tax_deferred_high']
        self.p_tax_deferred_low = params['p_tax_deferred_low']
        self.p_tax_deferred_weight_high = params['p_tax_deferred_weight_high']
        self.p_tax_deferred_weight_low = params['p_tax_deferred_weight_low']
        self.p_tax_free_high = params['p_tax_free_high']
        self.p_tax_free_low = params['p_tax_free_low']
        self.p_tax_free_weight_high = params['p_tax_free_weight_high']
        self.p_tax_free_weight_low = params['p_tax_free_weight_low']
        self.p_taxable_iid_bonds_basis = params['p_taxable_iid_bonds_basis']
        self.p_taxable_iid_bonds_basis_fraction_high = params['p_taxable_iid_bonds_basis_fraction_high']
        self.p_taxable_iid_bonds_basis_fraction_low = params['p_taxable_iid_bonds_basis_fraction_low']
        self.p_taxable_iid_bonds_high = params['p_taxable_iid_bonds_high']
        self.p_taxable_iid_bonds_low = params['p_taxable_iid_bonds_low']
        self.p_taxable_iid_bonds_weight_high = params['p_taxable_iid_bonds_weight_high']
        self.p_taxable_iid_bonds_weight_low = params['p_taxable_iid_bonds_weight_low']
        self.p_taxable_nominal_bonds_basis = params['p_taxable_nominal_bonds_basis']
        self.p_taxable_nominal_bonds_basis_fraction_high = params['p_taxable_nominal_bonds_basis_fraction_high']
        self.p_taxable_nominal_bonds_basis_fraction_low = params['p_taxable_nominal_bonds_basis_fraction_low']
        self.p_taxable_nominal_bonds_high = params['p_taxable_nominal_bonds_high']
        self.p_taxable_nominal_bonds_low = params['p_taxable_nominal_bonds_low']
        self.p_taxable_nominal_bonds_weight_high = params['p_taxable_nominal_bonds_weight_high']
        self.p_taxable_nominal_bonds_weight_low = params['p_taxable_nominal_bonds_weight_low']
        self.p_taxable_other_basis = params['p_taxable_other_basis']
        self.p_taxable_other_basis_fraction_high = params['p_taxable_other_basis_fraction_high']
        self.p_taxable_other_basis_fraction_low = params['p_taxable_other_basis_fraction_low']
        self.p_taxable_other_high = params['p_taxable_other_high']
        self.p_taxable_other_low = params['p_taxable_other_low']
        self.p_taxable_other_weight_high = params['p_taxable_other_weight_high']
        self.p_taxable_other_weight_low = params['p_taxable_other_weight_low']
        self.p_taxable_real_bonds_basis = params['p_taxable_real_bonds_basis']
        self.p_taxable_real_bonds_basis_fraction_high = params['p_taxable_real_bonds_basis_fraction_high']
        self.p_taxable_real_bonds_basis_fraction_low = params['p_taxable_real_bonds_basis_fraction_low']
        self.p_taxable_real_bonds_high = params['p_taxable_real_bonds_high']
        self.p_taxable_real_bonds_low = params['p_taxable_real_bonds_low']
        self.p_taxable_real_bonds_weight_high = params['p_taxable_real_bonds_weight_high']
        self.p_taxable_real_bonds_weight_low = params['p_taxable_real_bonds_weight_low']
        self.p_taxable_stocks_basis = params['p_taxable_stocks_basis']
        self.p_taxable_stocks_basis_fraction_high = params['p_taxable_stocks_basis_fraction_high']
        self.p_taxable_stocks_basis_fraction_low = params['p_taxable_stocks_basis_fraction_low']
        self.p_taxable_stocks_high = params['p_taxable_stocks_high']
        self.p_taxable_stocks_low = params['p_taxable_stocks_low']
        self.p_taxable_stocks_weight_high = params['p_taxable_stocks_weight_high']
        self.p_taxable_stocks_weight_low = params['p_taxable_stocks_weight_low']
        self.p_weighted_high = params['p_weighted_high']
        self.p_weighted_low = params['p_weighted_low']
        self.preretirement_spias = params['preretirement_spias']
        self.probabilistic_life_expectancy = params['probabilistic_life_expectancy']
        self.qualified_dividends_bonds = params['qualified_dividends_bonds']
        self.qualified_dividends_stocks = params['qualified_dividends_stocks']
        self.real_bonds = params['real_bonds']
        self.real_bonds_adjust = params['real_bonds_adjust']
        self.real_bonds_duration = params['real_bonds_duration']
        self.real_bonds_duration_action_force = params['real_bonds_duration_action_force']
        self.real_bonds_duration_max = params['real_bonds_duration_max']
        self.real_short_rate_type = params['real_short_rate_type']
        self.real_short_rate_value = params['real_short_rate_value']
        self.real_spias = params['real_spias']
        self.real_spias_mwr = params['real_spias_mwr']
        self.returns_standard_error = params['returns_standard_error']
        self.reward_clip = params['reward_clip']
        self.reward_warn = params['reward_warn']
        self.rl_consume_bias = params['rl_consume_bias']
        self.rl_stocks_bias = params['rl_stocks_bias']
        self.sex = params['sex']
        self.sex2 = params['sex2']
        self.spias_from_age = params['spias_from_age']
        self.spias_min_purchase_fraction = params['spias_min_purchase_fraction']
        self.spias_partial = params['spias_partial']
        self.spias_permitted_from_age = params['spias_permitted_from_age']
        self.spias_permitted_to_age = params['spias_permitted_to_age']
        self.static_bonds = params['static_bonds']
        self.stocks = params['stocks']
        self.stocks_alpha = params['stocks_alpha']
        self.stocks_beta = params['stocks_beta']
        self.stocks_bootstrap_years = params['stocks_bootstrap_years']
        self.stocks_gamma = params['stocks_gamma']
        self.stocks_mean_reversion_rate = params['stocks_mean_reversion_rate']
        self.stocks_model = params['stocks_model']
        self.stocks_mu = params['stocks_mu']
        self.stocks_price_exaggeration = params['stocks_price_exaggeration']
        self.stocks_price_high = params['stocks_price_high']
        self.stocks_price_low = params['stocks_price_low']
        self.stocks_price_noise_sigma = params['stocks_price_noise_sigma']
        self.stocks_return = params['stocks_return']
        self.stocks_sigma = params['stocks_sigma']
        self.stocks_sigma_level_type = params['stocks_sigma_level_type']
        self.stocks_sigma_level_value = params['stocks_sigma_level_value']
        self.stocks_sigma_max = params['stocks_sigma_max']
        self.stocks_standard_error = params['stocks_standard_error']
        self.stocks_volatility = params['stocks_volatility']
        self.tax = params['tax']
        self.tax_fixed = params['tax_fixed']
        self.tax_inflation_adjust_all = params['tax_inflation_adjust_all']
        self.tax_state = params['tax_state']
        self.tax_table_year = params['tax_table_year']
        self.time_period = params['time_period']
        self.verbose = params['verbose']
        self.warn = params['warn']
        self.welfare = params['welfare']
