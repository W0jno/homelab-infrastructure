# Debian LXC template is not present on pve2 by default; fetch it there.
resource "proxmox_download_file" "immich_template" {
  node_name    = var.immich.node_name
  datastore_id = "local"
  content_type = "vztmpl"
  url          = var.immich.template_url
}

resource "proxmox_virtual_environment_container" "immich" {
  node_name     = var.immich.node_name
  vm_id         = var.immich.vm_id
  unprivileged  = true
  start_on_boot = true

  features {
    nesting = true # required for Docker inside the LXC
  }

  operating_system {
    template_file_id = proxmox_download_file.immich_template.id
    type             = "debian"
  }

  disk {
    datastore_id = var.immich.photos_datastore
    size         = var.immich.disk_size
  }

  cpu {
    cores = var.immich.cores
  }

  memory {
    dedicated = var.immich.memory
    swap      = var.immich.swap
  }

  # Photo library lives on its own volume, separate from the container rootfs.
  mount_point {
    volume = var.immich.photos_datastore
    size   = "${var.immich.photos_size}G"
    path   = var.immich.photos_path
  }

  network_interface {
    name   = "eth0"
    bridge = "vmbr0"
  }

  initialization {
    hostname = var.immich.hostname

    ip_config {
      ipv4 {
        address = var.immich.ip
        gateway = var.immich.gateway
      }
    }

    user_account {
      keys = [var.ssh_ubuntu_key]
    }
  }

  lifecycle {
    # Photos live on the mount point volume; never destroy/replace this container.
    prevent_destroy = true
    # Template is only used at creation time.
    ignore_changes = [operating_system[0].template_file_id]
  }
}
