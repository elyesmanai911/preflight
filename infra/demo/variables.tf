variable "subscription_id" {
  type = string
}

variable "ssh_source_ip" {
  description = "Your public IP; the only address allowed to SSH in."
  type        = string
}

variable "github_token" {
  description = "Token for the triage watcher (fine-grained, this repo, PR read/write). Pass via TF_VAR_github_token."
  type        = string
  sensitive   = true
}

variable "llm_api_key" {
  description = "Gemini API key for the agents. Pass via TF_VAR_llm_api_key."
  type        = string
  sensitive   = true
}

variable "vm_size" {
  type = string
  # 2 vCPU, 4 GiB, ~$0.0416/h in East US. Azure retires B-series v1 on 2028-11-15 and gives new
  # subscriptions no quota for it; this one still has some, so main.tf silences TFLint's
  # retired-size notice. The same-price successor, B2ls_v2, needs a Bsv2 quota request first
  # (this subscription has 0).
  default = "Standard_B2s"
}

variable "zone" {
  description = "Availability zone; pin one when the region has no capacity for vm_size."
  type        = string
  default     = null
}
