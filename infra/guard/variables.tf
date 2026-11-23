variable "subscription_id" {
  type = string
}

variable "alert_email" {
  description = "Where budget alerts go. Set it in terraform.tfvars (git-ignored), never in the repo."
  type        = string
  sensitive   = true
}

variable "location" {
  type    = string
  default = "eastus" # B2s list price $0.0416/h here, the figure the cost line uses
}

variable "ttl" {
  description = "Lifetime of the demo resource group, counted from when this stack's clock starts."
  type        = string
  default     = "72h"
}

variable "cap_usd" {
  description = "The hard line. The kill switch fires at half of it, leaving margin for billing-data lag."
  type        = number
  default     = 10
}
