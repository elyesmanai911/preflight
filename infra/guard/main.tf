# Cost guards for the Azure demo. Built and tested BEFORE anything billable exists.
#
#   1. Everything billable lives in ONE resource group, preflight-demo.
#   2. Self-destruct: a Logic App deletes preflight-demo once it is older than var.ttl.
#      Doesn't depend on billing data, which can lag a day (or not exist yet on a new subscription).
#   3. Kill switch: subscription budget at 50% of var.cap_usd -> action group -> Logic App deletes preflight-demo.
#   4. Emails at 30% actual, 50% actual, and 80% forecast.

data "azurerm_subscription" "current" {}

resource "azurerm_resource_group" "guard" {
  name     = "preflight-guard"
  location = var.location
}

# The clock for the self-destruct. Restart it with: terraform apply -replace=time_static.demo_clock
resource "time_static" "demo_clock" {}

locals {
  expires_at = timeadd(time_static.demo_clock.rfc3339, var.ttl)
  delete_demo_rg = {
    type = "Http"
    # Don't poll the async delete: the Logic App's permission lives on the group being deleted,
    # so polling ends in 403 even though the delete succeeded. 202 Accepted = success.
    operationOptions = "DisableAsyncPattern"
    inputs = {
      method = "DELETE"
      uri    = "https://management.azure.com${azurerm_resource_group.demo.id}?api-version=2021-04-01"
      authentication = {
        type     = "ManagedServiceIdentity"
        audience = "https://management.azure.com/"
      }
    }
  }
}

resource "azurerm_resource_group" "demo" {
  name     = "preflight-demo"
  location = var.location
  tags = {
    purpose    = "preflight cloud demo"
    expires_at = local.expires_at
  }
}

# ---------- Self-destruct (time-based) ----------

resource "azurerm_logic_app_workflow" "self_destruct" {
  name                = "preflight-self-destruct"
  location            = azurerm_resource_group.guard.location
  resource_group_name = azurerm_resource_group.guard.name
  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_logic_app_trigger_recurrence" "hourly" {
  name         = "hourly"
  logic_app_id = azurerm_logic_app_workflow.self_destruct.id
  frequency    = "Hour"
  interval     = 1
}

resource "azurerm_logic_app_action_custom" "delete_if_expired" {
  name         = "delete_if_expired"
  logic_app_id = azurerm_logic_app_workflow.self_destruct.id
  body = jsonencode({
    type = "If"
    expression = {
      and = [{ greater = ["@ticks(utcNow())", "@ticks('${local.expires_at}')"] }]
    }
    actions  = { delete_demo_rg = local.delete_demo_rg }
    runAfter = {}
  })
}

# ---------- Kill switch (budget-based) ----------

resource "azurerm_logic_app_workflow" "kill_switch" {
  name                = "preflight-kill-switch"
  location            = azurerm_resource_group.guard.location
  resource_group_name = azurerm_resource_group.guard.name
  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_logic_app_trigger_http_request" "budget_alert" {
  name         = "budget_alert"
  logic_app_id = azurerm_logic_app_workflow.kill_switch.id
  schema       = "{}"
}

resource "azurerm_logic_app_action_custom" "delete_now" {
  name         = "delete_demo_rg"
  logic_app_id = azurerm_logic_app_workflow.kill_switch.id
  body         = jsonencode(merge(local.delete_demo_rg, { runAfter = {} }))
}

# Both Logic Apps may delete ONLY the demo resource group.
resource "azurerm_role_assignment" "self_destruct" {
  scope                = azurerm_resource_group.demo.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_logic_app_workflow.self_destruct.identity[0].principal_id
}

resource "azurerm_role_assignment" "kill_switch" {
  scope                = azurerm_resource_group.demo.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_logic_app_workflow.kill_switch.identity[0].principal_id
}

resource "azurerm_monitor_action_group" "kill" {
  name                = "preflight-kill"
  resource_group_name = azurerm_resource_group.guard.name
  short_name          = "pf-kill"

  email_receiver {
    name          = "owner"
    email_address = var.alert_email
  }

  logic_app_receiver {
    name                    = "kill-switch"
    resource_id             = azurerm_logic_app_workflow.kill_switch.id
    callback_url            = azurerm_logic_app_trigger_http_request.budget_alert.callback_url
    use_common_alert_schema = true
  }
}

resource "azurerm_consumption_budget_subscription" "cap" {
  name            = "preflight-cap"
  subscription_id = data.azurerm_subscription.current.id
  amount          = var.cap_usd
  time_grain      = "Annually"

  time_period {
    start_date = "2026-11-01T00:00:00Z"
  }

  notification {
    enabled        = true
    operator       = "GreaterThan"
    threshold      = 30
    threshold_type = "Actual"
    contact_emails = [var.alert_email]
  }

  notification { # the kill switch
    enabled        = true
    operator       = "GreaterThan"
    threshold      = 50
    threshold_type = "Actual"
    contact_groups = [azurerm_monitor_action_group.kill.id]
  }

  notification {
    enabled        = true
    operator       = "GreaterThan"
    threshold      = 80
    threshold_type = "Forecasted"
    contact_emails = [var.alert_email]
  }
}
