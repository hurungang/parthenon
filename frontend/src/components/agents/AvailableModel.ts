/**
 * Shared shape for a configured model that an operator can attach a guardrail
 * to. The model name is the primary identifier on the wire; `model_config_id`
 * is the FK to the vendor `ModelConfig` row. The two legacy `config_id` /
 * `provider_type` fields are preserved for back-compat with existing dialog
 * code.
 */
export interface AvailableModel {
  model_id: string
  model_name: string
  /** FK to the vendor ModelConfig; preferred for new guardrail payloads. */
  model_config_id: string
  /** Legacy alias for `model_config_id`; kept for back-compat. */
  config_id: string
  config_display_name: string
  provider_type: string
}
