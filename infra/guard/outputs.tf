output "demo_resource_group" {
  value = azurerm_resource_group.demo.name
}

output "demo_expires_at" {
  value = local.expires_at
}

output "kill_switch_url" {
  value     = azurerm_logic_app_trigger_http_request.budget_alert.callback_url
  sensitive = true
}
