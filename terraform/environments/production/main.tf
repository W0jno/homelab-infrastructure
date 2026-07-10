resource "proxmox_virtual_environment_vm" "production" {
  node_name = "pve"
  name      = "cv-test-01"
  vm_id     = 9001
  stop_on_destroy = true
  clone {
    vm_id = 9000
    full  = true
  }

  network_device {
    bridge = "vmbr0"
  } 
  initialization {
    user_account {
      username = "ubuntu"
      keys = [var.ssh_ubuntu_key]
    }
    ip_config {
      ipv4 {
        address = "192.168.1.201/24"
        gateway = "192.168.1.1"
      }
    }
  }

}