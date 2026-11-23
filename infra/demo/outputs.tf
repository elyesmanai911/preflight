output "public_ip" {
  value = azurerm_public_ip.demo.ip_address
}

output "preview_domain" {
  value = "preview.${local.domain}"
}

output "ssh" {
  value = "ssh -i ~/.ssh/preflight_azure preflight@${azurerm_public_ip.demo.ip_address}"
}

output "kubectl_tunnel" {
  value = "ssh -i ~/.ssh/preflight_azure -N -L 6443:127.0.0.1:6443 preflight@${azurerm_public_ip.demo.ip_address}"
}
