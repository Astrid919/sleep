# Reproduction comparison

{"base_pass": 18, "base_total": 18, "extension_pass": 21, "extension_total": 21, "figures_pass": 0, "figures_total": 8}

## base_tsv

- PASS: bayesian_shrinkage_sensitivity.tsv; max numeric difference=4.31e-13; exact bytes=False
- PASS: causal_models_sleep_categories.tsv; max numeric difference=6.28e-13; exact bytes=False
- PASS: causal_models_sleep_categories_summary.tsv; max numeric difference=1.54e-11; exact bytes=False
- PASS: causal_models_sleep_rcs_curve.tsv; max numeric difference=2.67e-12; exact bytes=False
- PASS: causal_models_sleep_rcs_summary.tsv; max numeric difference=4.06e-11; exact bytes=False
- PASS: causal_reanalysis_quality_control.tsv; max numeric difference=0; exact bytes=True
- PASS: competing_risk_fine_gray.tsv; max numeric difference=1.19e-13; exact bytes=False
- PASS: competing_risk_fine_gray_summary.tsv; max numeric difference=7.99e-13; exact bytes=False
- PASS: flexible_covariate_knots.tsv; max numeric difference=0; exact bytes=True
- PASS: inflammation_outcome_pathway.tsv; max numeric difference=1.11e-13; exact bytes=False
- PASS: inflammation_sleep_categories.tsv; max numeric difference=1.52e-12; exact bytes=False
- PASS: inflammation_sleep_rcs_curve.tsv; max numeric difference=2.77e-12; exact bytes=False
- PASS: inflammation_sleep_rcs_summary.tsv; max numeric difference=2.69e-11; exact bytes=False
- PASS: multiple_imputation_individual_estimates.tsv; max numeric difference=1.36e-13; exact bytes=False
- PASS: multiple_imputation_rubin_pooled.tsv; max numeric difference=2.04e-14; exact bytes=False
- PASS: multiple_imputation_specification.tsv; max numeric difference=0; exact bytes=True
- PASS: multiple_imputation_summary.tsv; max numeric difference=3.41e-13; exact bytes=False
- PASS: reverse_causation_lag_24_months.tsv; max numeric difference=1.71e-13; exact bytes=False

## extension_tsv

- PASS: alternative_4knot_sleep_rcs_curve.tsv; max numeric difference=1.31e-12; exact bytes=False
- PASS: alternative_4knot_sleep_rcs_summary.tsv; max numeric difference=2.81e-11; exact bytes=False
- PASS: e_values_long_sleep.tsv; max numeric difference=4.93e-14; exact bytes=False
- PASS: follow_up_and_event_summary.tsv; max numeric difference=0; exact bytes=True
- PASS: health_status_domain_one_at_a_time.tsv; max numeric difference=3.61e-13; exact bytes=False
- PASS: health_status_sequential_attenuation.tsv; max numeric difference=4.33e-13; exact bytes=False
- PASS: leave_one_cycle_out_long_sleep.tsv; max numeric difference=1.09e-13; exact bytes=False
- PASS: proportional_hazards_piecewise_models.tsv; max numeric difference=2.03e-12; exact bytes=False
- PASS: proportional_hazards_time_interaction.tsv; max numeric difference=9.47e-13; exact bytes=False
- PASS: proportional_hazards_time_specific_HR.tsv; max numeric difference=6.08e-12; exact bytes=False
- PASS: quantitative_bias_contour_grid.tsv; max numeric difference=6.66e-15; exact bytes=False
- PASS: reverse_causation_lag_2y_5y.tsv; max numeric difference=1.71e-13; exact bytes=False
- PASS: same_cycle_composition_lag_0y_2y_5y.tsv; max numeric difference=4.07e-12; exact bytes=False
- PASS: standardized_absolute_risk_contrasts.tsv; max numeric difference=1.04e-14; exact bytes=False
- PASS: standardized_absolute_risk_horizons.tsv; max numeric difference=1.24e-14; exact bytes=False
- PASS: standardized_cif_bootstrap_diagnostics.tsv; max numeric difference=0; exact bytes=True
- PASS: standardized_cumulative_incidence_curve.tsv; max numeric difference=2.32e-16; exact bytes=False
- PASS: survey_design_audit.tsv; max numeric difference=0; exact bytes=True
- PASS: survey_design_cycle_inventory.tsv; max numeric difference=0; exact bytes=True
- PASS: survey_design_estimate_comparison.tsv; max numeric difference=1.77e-12; exact bytes=False
- PASS: survey_validated_extension_quality_control.tsv; max numeric difference=0; exact bytes=True

## figures

- REVIEW: Figure1_causal_dag.png
- REVIEW: Figure2_sleep_mortality_rcs.png
- REVIEW: Figure3_inflammation_pathway_rcs.png
- REVIEW: Figure3_health_status_domain_attenuation.png
- REVIEW: Figure4_robustness_forest.png
- REVIEW: Figure5_standardized_cumulative_incidence.png
- REVIEW: FigureS_bias_contour.png
- REVIEW: FigureS_PH_time_specific_HR.png
