# TFLint for infra/demo and infra/guard (CI runs it in each). Catches what `terraform validate`
# can't: unused variables, missing types, deprecated syntax, invalid Azure VM sizes or regions.
config {
  call_module_type = "local"
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "azurerm" {
  enabled = true
  version = "0.33.0"
  source  = "github.com/terraform-linters/tflint-ruleset-azurerm"
}

# The demo is built to be destroyed after each recording (and the guards may delete it at any
# time), so prevent_destroy would only get in the way.
rule "azurerm_resources_missing_prevent_destroy" {
  enabled = false
}
