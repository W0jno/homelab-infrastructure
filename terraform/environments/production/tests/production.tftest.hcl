# Plan-only tests on a mocked provider: no Proxmox, no credentials, runs in CI.
# Proves that the code, given the thesis topology, produces the designed resources.

mock_provider "proxmox" {}

variables {
  proxmox_endpoint  = "https://pve.test:8006/"
  proxmox_api_token = "terraform@pve!test=not-a-real-token"
  ssh_ubuntu_key    = "ssh-ed25519 AAAATEST test"

  k3s_nodes = {
    "k3s-master"    = { vm_id = 201, vm_name = "k3s-master", vm_ip = "192.168.1.201", vm_gateway = "192.168.1.1", vm_netmask = "24", vm_dns = "1.1.1.1", memory = 4096, cores = 2 }
    "k3s-worker-01" = { vm_id = 202, vm_name = "k3s-worker-01", vm_ip = "192.168.1.202", vm_gateway = "192.168.1.1", vm_netmask = "24", vm_dns = "1.1.1.1", memory = 4096, cores = 2 }
    "k3s-worker-02" = { vm_id = 203, vm_name = "k3s-worker-02", vm_ip = "192.168.1.203", vm_gateway = "192.168.1.1", vm_netmask = "24", vm_dns = "1.1.1.1", memory = 4096, cores = 2 }
  }

  immich = {
    vm_id            = 8100
    node_name        = "pve2"
    hostname         = "immich"
    template_url     = "http://download.proxmox.com/images/system/debian-13-standard_13.1-2_amd64.tar.zst"
    ip               = "192.168.1.168/24"
    gateway          = "192.168.1.1"
    memory           = 4096
    swap             = 2048
    cores            = 4
    disk_size        = 16
    photos_datastore = "local-lvm"
    photos_size      = 35
    photos_path      = "/mnt/photos"
  }
}

run "k3s_cluster_is_three_vms_from_cloud_init_template" {
  command = plan

  assert {
    condition     = length(proxmox_virtual_environment_vm.k3s) == 3
    error_message = "Expected 3 k3s VMs (1 control plane + 2 agents)."
  }

  assert {
    condition     = alltrue([for vm in proxmox_virtual_environment_vm.k3s : vm.clone[0].full])
    error_message = "Every k3s VM must be a full clone of cloud-init template 9000."
  }

  assert {
    condition     = alltrue([for vm in proxmox_virtual_environment_vm.k3s : vm.node_name == "pve" && vm.network_device[0].bridge == "vmbr0"])
    error_message = "k3s VMs must run on node pve, bridged to vmbr0."
  }

  assert {
    condition = toset([for vm in proxmox_virtual_environment_vm.k3s : vm.initialization[0].ip_config[0].ipv4[0].address]) == toset([
      "192.168.1.201/24", "192.168.1.202/24", "192.168.1.203/24",
    ])
    error_message = "k3s VMs must get the static IPs from the architecture diagram."
  }
}

run "ssh_keys_are_injected_by_cloud_init" {
  command = plan

  assert {
    condition     = alltrue([for vm in proxmox_virtual_environment_vm.k3s : vm.initialization[0].user_account[0].keys == tolist([var.ssh_ubuntu_key])])
    error_message = "k3s VMs must receive the SSH key via cloud-init user_account."
  }

  assert {
    condition     = alltrue([for vm in proxmox_virtual_environment_vm.k3s : vm.initialization[0].user_account[0].password == null])
    error_message = "k3s VMs must not use password authentication."
  }

  assert {
    condition     = proxmox_virtual_environment_container.immich.initialization[0].user_account[0].keys == tolist([var.ssh_ubuntu_key])
    error_message = "Immich LXC must receive the SSH key at creation time."
  }
}

run "immich_is_unprivileged_lxc_on_pve2_separate_from_k3s" {
  command = plan

  assert {
    condition     = proxmox_virtual_environment_container.immich.unprivileged
    error_message = "Immich LXC must be unprivileged (container root is not host root)."
  }

  assert {
    condition     = proxmox_virtual_environment_container.immich.node_name == "pve2" && proxmox_download_file.immich_template.node_name == "pve2"
    error_message = "Immich LXC and its template must live on node pve2."
  }

  assert {
    condition     = proxmox_virtual_environment_container.immich.initialization[0].ip_config[0].ipv4[0].address == "192.168.1.168/24"
    error_message = "Immich LXC must get the static IP 192.168.1.168."
  }

  assert {
    condition     = proxmox_virtual_environment_container.immich.mount_point[0].path == "/mnt/photos"
    error_message = "Photo library must be mounted at /mnt/photos on its own volume."
  }

  assert {
    condition     = !contains([for vm in proxmox_virtual_environment_vm.k3s : vm.vm_id], proxmox_virtual_environment_container.immich.vm_id)
    error_message = "Immich LXC must not share a VMID with the k3s cluster."
  }
}

run "template_and_all_lxcs_are_defined_in_code" {
  command = plan

  assert {
    condition     = proxmox_virtual_environment_vm.ubuntu_template.vm_id == 9000 && proxmox_virtual_environment_vm.ubuntu_template.template
    error_message = "The k3s cloud-init template (VMID 9000) must be managed by Terraform."
  }

  assert {
    condition     = proxmox_download_file.ubuntu_cloud_image.content_type == "import"
    error_message = "The template disk must come from a downloaded cloud image, not a manual import."
  }

  assert {
    condition     = toset([for c in proxmox_virtual_environment_container.service : c.vm_id]) == toset([100, 102, 104, 105, 106])
    error_message = "All pre-existing service LXCs must be defined in code."
  }

  assert {
    condition     = alltrue([for c in proxmox_virtual_environment_container.service : c.unprivileged])
    error_message = "Every service LXC must be unprivileged."
  }
}
