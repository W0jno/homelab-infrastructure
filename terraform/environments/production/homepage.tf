# Homepage dashboard LXC on node pve. Stateless: all configuration comes from
# the Ansible role `homepage`, so the container can be rebuilt at any time.
locals {
  homepage = {
    vm_id     = 107
    hostname  = "homepage"
    ip        = "192.168.1.204/24"
    gateway   = "192.168.1.1"
    dns       = "192.168.1.1"
    cores     = 1
    memory    = 512
    swap      = 512
    disk_size = 8
  }
}

resource "proxmox_virtual_environment_container" "homepage" {
  node_name     = "pve"
  vm_id         = local.homepage.vm_id
  unprivileged  = true
  start_on_boot = true

  features {
    nesting = true # required for Docker inside the LXC
  }

  operating_system {
    # Same Debian template the other service LXCs on pve were created from.
    template_file_id = "local:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst"
    type             = "debian"
  }

  disk {
    datastore_id = "local-lvm"
    size         = local.homepage.disk_size
  }

  cpu {
    cores = local.homepage.cores
  }

  memory {
    dedicated = local.homepage.memory
    swap      = local.homepage.swap
  }

  network_interface {
    name   = "eth0"
    bridge = "vmbr0"
  }

  initialization {
    hostname = local.homepage.hostname

    dns {
      servers = [local.homepage.dns]
    }

    ip_config {
      ipv4 {
        address = local.homepage.ip
        gateway = local.homepage.gateway
      }
    }

    user_account {
      keys = [var.ssh_ubuntu_key]
    }
  }

  lifecycle {
    # Template is only used at creation time.
    ignore_changes = [operating_system[0].template_file_id]
  }
}
