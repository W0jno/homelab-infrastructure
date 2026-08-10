output "k3s_vm_ids" {
  description = "The IDs of the K3s VMs"
  value = {
    for name, vm in proxmox_virtual_environment_vm.k3s : name => vm.vm_id
  }
}

output "k3s_ips" {
  description = "Static IPs assigned to k3s nodes"
  value = {
    for name, node in var.k3s_nodes : name => node.vm_ip
  }
}

output "k3s_nodes" {
  description = "Summary of k3s nodes"
  value = {
    for name, node in var.k3s_nodes :
    name => {
      vm_id = node.vm_id
      name  = node.vm_name
      ip    = node.vm_ip
    }
  }
}

output "media" {
  description = "Home cinema LXC summary"
  value = {
    vm_id    = proxmox_virtual_environment_container.media.vm_id
    hostname = var.media.hostname
    ip       = var.media.ip
  }
}
