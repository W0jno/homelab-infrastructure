# Pre-existing service LXCs on node pve, imported into Terraform so their
# Proxmox-level definition (resources, disk, network) lives in code.
# Values are not secret, so they stay in git instead of the ignored tfvars.
locals {
  service_lxcs = {
    pihole-backup = {
      vm_id = 100, cores = 1, memory = 512, swap = 512, disk_size = 8
      ip    = "192.168.1.28/24", gateway = "192.168.1.1", mac = "BC:24:11:93:7B:92"
    }
    home-tools-1 = {
      vm_id = 102, cores = 2, memory = 4096, swap = 1024, disk_size = 30
      ip    = "192.168.1.101/24", gateway = "192.168.1.1", mac = "BC:24:11:5C:FC:8A"
    }
    npm-proxy = {
      vm_id = 104, cores = 1, memory = 256, swap = 256, disk_size = 8
      ip    = "192.168.1.30/24", gateway = "192.168.1.1", mac = "BC:24:11:3A:9F:38"
    }
    vaultwarden = {
      vm_id = 105, cores = 1, memory = 512, swap = 512, disk_size = 12
      ip    = "192.168.1.40/24", gateway = "192.168.1.1", mac = "BC:24:11:8B:0F:56"
    }
    home-obsidian-db-1 = {
      vm_id = 106, cores = 1, memory = 512, swap = 512, disk_size = 8
      ip    = "dhcp", gateway = null, mac = "BC:24:11:9D:2E:67"
    }
  }
}


resource "proxmox_virtual_environment_container" "service" {
  for_each = local.service_lxcs

  node_name    = "pve"
  vm_id        = each.value.vm_id
  unprivileged = true
  # Matches the current setting; these containers are not started on host boot.
  start_on_boot = false

  console {
    enabled   = true
    tty_count = 2
    type      = "tty"
  }

  features {
    nesting = true
  }

  operating_system {
    template_file_id = "local:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst"
    type             = "debian"
  }

  disk {
    datastore_id = "local-lvm"
    size         = each.value.disk_size
  }

  cpu {
    cores = each.value.cores
  }

  memory {
    dedicated = each.value.memory
    swap      = each.value.swap
  }

  network_interface {
    name        = "eth0"
    bridge      = "vmbr0"
    firewall    = true
    mac_address = each.value.mac
  }

  initialization {
    hostname = each.key

    ip_config {
      ipv4 {
        address = each.value.ip
        gateway = each.value.gateway
      }
    }
  }

  lifecycle {
    # Service data lives on the rootfs; never destroy/replace these containers.
    prevent_destroy = true
    # Imported: the original template and SSH keys are creation-time only.
    ignore_changes = [operating_system, initialization[0].user_account]
  }
}
