# The cloud demo: one VM, configured by Ansible (infra/ansible) once Terraform has created it.
# Lives ONLY in preflight-demo, the resource group the guards (infra/guard) can delete at any time.

data "azurerm_resource_group" "demo" {
  name = "preflight-demo"
}

data "azurerm_client_config" "current" {}

locals {
  location = data.azurerm_resource_group.demo.location
  rg       = data.azurerm_resource_group.demo.name
  domain   = "${azurerm_public_ip.demo.ip_address}.nip.io"
  vault    = "preflight-${substr(md5(var.subscription_id), 0, 8)}"
}

# ---------- Network ----------

resource "azurerm_virtual_network" "demo" {
  name                = "preflight-vnet"
  location            = local.location
  resource_group_name = local.rg
  address_space       = ["10.20.0.0/16"]
}

resource "azurerm_subnet" "demo" {
  name                 = "default"
  resource_group_name  = local.rg
  virtual_network_name = azurerm_virtual_network.demo.name
  address_prefixes     = ["10.20.1.0/24"]

  service_endpoint { # lets the Key Vault firewall allow this subnet
    service = "Microsoft.KeyVault"
  }
}

resource "azurerm_network_security_group" "demo" {
  #checkov:skip=CKV_AZURE_160:previews are public on purpose; HTTP only, no secrets in them
  name                = "preflight-nsg"
  location            = local.location
  resource_group_name = local.rg

  security_rule {
    name                       = "ssh-from-owner-only"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = "${var.ssh_source_ip}/32"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "http-previews"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
  # Everything else, including the Kubernetes API (6443), stays closed: use an SSH tunnel.
}

resource "azurerm_subnet_network_security_group_association" "demo" {
  subnet_id                 = azurerm_subnet.demo.id
  network_security_group_id = azurerm_network_security_group.demo.id
}

resource "azurerm_public_ip" "demo" {
  name                = "preflight-ip"
  location            = local.location
  resource_group_name = local.rg
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_network_interface" "demo" {
  #checkov:skip=CKV_AZURE_119:the VM serves the previews itself; a load balancer would cost more
  name                = "preflight-nic"
  location            = local.location
  resource_group_name = local.rg

  ip_configuration {
    name                          = "primary"
    subnet_id                     = azurerm_subnet.demo.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.demo.id
  }
}

# ---------- Secrets: Key Vault, read by the VM's own identity ----------

# Purge protection would block reusing the vault name for days after each destroy; soft delete
# (7 days) still applies. A private endpoint costs ~$7/month; the firewall below gets most of the
# benefit for free: only this subnet and the owner's IP can reach the vault.
resource "azurerm_key_vault" "demo" {
  #checkov:skip=CKV_AZURE_110:demo vault is destroyed and recreated with the same name
  #checkov:skip=CKV_AZURE_42:recoverable needs purge protection, see above
  #checkov:skip=CKV2_AZURE_32:private endpoint is paid; firewall + service endpoint instead
  name                       = local.vault
  location                   = local.location
  resource_group_name        = local.rg
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  soft_delete_retention_days = 7
  purge_protection_enabled   = false

  network_acls {
    default_action             = "Deny"
    bypass                     = "AzureServices"
    ip_rules                   = [var.ssh_source_ip]      # Terraform writes the secrets from here
    virtual_network_subnet_ids = [azurerm_subnet.demo.id] # the VM reads them from here
  }
}

# Secrets expire after 30 days; the next terraform apply after that sets a new date.
resource "time_rotating" "secrets" {
  rotation_days = 30
}

resource "azurerm_role_assignment" "me_writes_secrets" {
  scope                = azurerm_key_vault.demo.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_key_vault_secret" "github_token" {
  name            = "github-token"
  value           = var.github_token
  content_type    = "text/plain"
  expiration_date = time_rotating.secrets.rotation_rfc3339
  key_vault_id    = azurerm_key_vault.demo.id
  depends_on      = [azurerm_role_assignment.me_writes_secrets]
}

resource "azurerm_key_vault_secret" "llm_api_key" {
  name            = "llm-api-key"
  value           = var.llm_api_key
  content_type    = "text/plain"
  expiration_date = time_rotating.secrets.rotation_rfc3339
  key_vault_id    = azurerm_key_vault.demo.id
  depends_on      = [azurerm_role_assignment.me_writes_secrets]
}

resource "azurerm_role_assignment" "vm_reads_secrets" {
  scope                = azurerm_key_vault.demo.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_virtual_machine.demo.identity[0].principal_id
}

# ---------- The VM ----------

resource "azurerm_linux_virtual_machine" "demo" {
  name                  = "preflight-vm"
  location              = local.location
  resource_group_name   = local.rg
  size                  = var.vm_size # tflint-ignore: azurerm_linux_virtual_machine_retired_size
  zone                  = var.zone
  admin_username        = "preflight"
  network_interface_ids = [azurerm_network_interface.demo.id]

  allow_extension_operations = false # Ansible configures the VM, no Azure extensions

  admin_ssh_key {
    username   = "preflight"
    public_key = file(pathexpand("~/.ssh/preflight_azure.pub"))
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 30
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  identity {
    type = "SystemAssigned"
  }
}

# Stops compute billing every night, in case the demo is forgotten.
resource "azurerm_dev_test_global_vm_shutdown_schedule" "nightly" {
  virtual_machine_id    = azurerm_linux_virtual_machine.demo.id
  location              = local.location
  enabled               = true
  daily_recurrence_time = "2300"
  timezone              = "W. Central Africa Standard Time" # Tunis
  notification_settings {
    enabled = false
  }
}

# Everything Ansible needs to reach and configure the VM. Holds no secrets: the VM reads those
# from Key Vault itself.
resource "local_file" "ansible_inventory" {
  filename        = "${path.module}/../ansible/inventory/demo.yml"
  file_permission = "0600"
  content = yamlencode({
    demo = {
      hosts = {
        preflight-vm = {
          ansible_host                 = azurerm_public_ip.demo.ip_address
          ansible_user                 = "preflight"
          ansible_ssh_private_key_file = pathexpand("~/.ssh/preflight_azure")
          platform_preview_domain      = "preview.${local.domain}"
          secrets_vault_name           = local.vault
        }
      }
    }
  })
}
