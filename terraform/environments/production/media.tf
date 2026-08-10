resource "proxmox_virtual_environment_container" "media" {
  node_name    = "pve"
  vm_id        = var.media.vm_id
  unprivileged = true

  features {
    nesting = true
  }

  operating_system {
    template_file_id = var.media.template_file_id
    type             = "debian"
  }

  disk {
    datastore_id = "local-lvm"
    size         = var.media.disk_size
  }

  cpu {
    cores = var.media.cores
  }

  memory {
    dedicated = var.media.memory
  }

  mount_point {
    volume = var.media.media_datastore
    size   = var.media.media_size
    path   = var.media.media_mount_path
  }

  network_interface {
    name   = "eth0"
    bridge = "vmbr0"
  }

  initialization {
    hostname = var.media.hostname

    ip_config {
      ipv4 {
        address = var.media.ip
        gateway = var.media.gateway
      }
    }

    user_account {
      keys = [var.ssh_ubuntu_key]
    }
  }
}
