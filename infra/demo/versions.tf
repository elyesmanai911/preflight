terraform {
  required_version = ">= 1.9"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "5.13.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "0.14.2" # same as infra/guard
    }
    local = {
      source  = "hashicorp/local"
      version = "2.6.1"
    }
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy = true # so the vault name is reusable after destroy
    }
  }
  subscription_id = var.subscription_id
}
