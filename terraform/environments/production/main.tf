resource "proxmox_cloned_vm" "production" {
  node_name = "pve"
  name      = "cv-test-01"
  id     = 9001

  clone = {
    source_vm_id = 9000
    full         = true
  }
}