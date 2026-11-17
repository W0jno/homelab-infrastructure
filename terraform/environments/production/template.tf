# Ubuntu cloud-init template (VMID 9000) that the k3s VMs are full-cloned from.
# Defined here so a fresh Proxmox node needs no manual `qm importdisk`.
resource "proxmox_download_file" "ubuntu_cloud_image" {
  node_name    = "pve"
  datastore_id = "local"
  content_type = "import"
  url          = "https://cloud-images.ubuntu.com/releases/22.04/release/ubuntu-22.04-server-cloudimg-amd64.img"
  file_name    = "jammy-server-cloudimg-amd64.qcow2"
}


resource "proxmox_virtual_environment_vm" "ubuntu_template" {
  node_name = "pve"
  vm_id     = 9000
  name      = "ubuntu-cloud-template"
  template  = true
  started   = false
  on_boot   = false

  agent {
    enabled = true
  }

  cpu {
    cores = 2
  }

  memory {
    dedicated = 2048
  }

  scsi_hardware = "virtio-scsi-pci"

  disk {
    interface    = "scsi0"
    datastore_id = "local-lvm"
    import_from  = proxmox_download_file.ubuntu_cloud_image.id
  }

  initialization {
    datastore_id = "local-lvm"
    interface    = "ide2"
    user_account {
      username = "ubuntu"
    }
  }

  network_device {
    bridge = "vmbr0"
  }

  serial_device {}

  vga {
    type = "serial0"
  }

  lifecycle {
    # k3s VMs are full clones, but keep the template stable once it exists.
    prevent_destroy = true
    # Imported template: its disk was created from an earlier image build.
    ignore_changes = [disk[0].import_from, initialization, operating_system]
  }
}
