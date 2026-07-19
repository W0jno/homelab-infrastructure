resource "proxmox_virtual_environment_vm" "k3s" {
  for_each = var.k3s_nodes

  node_name       = "pve"
  name            = each.value.vm_name
  vm_id           = each.value.vm_id
  stop_on_destroy = true
  clone {
    vm_id = 9000
    full  = true
  }

  disk {
    interface = "scsi0"
    size = 10
    datastore_id = "local-lvm"
  }

  network_device {
    bridge = "vmbr0"
  }
  initialization {
    user_account {
      username = "ubuntu"
      keys     = [var.ssh_ubuntu_key]
    }
    dns {
      servers = [each.value.vm_dns]
    }
    ip_config {
      ipv4 {
        address = "${each.value.vm_ip}/${each.value.vm_netmask}"
        gateway = each.value.vm_gateway
      }
    }
  }

}