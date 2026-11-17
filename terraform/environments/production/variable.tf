variable "proxmox_endpoint" {
  type        = string
  description = "The endpoint of the Proxmox VE API"
}

variable "proxmox_api_token" {
  type        = string
  description = "The API token for the Proxmox VE API"
}

variable "ssh_ubuntu_key" {
  type        = string
  description = "The SSH key for the Ubuntu user"
}

variable "k3s_nodes" {
  type = map(object({
    vm_id      = number
    vm_name    = string
    vm_ip      = string
    vm_gateway = string
    vm_netmask = string
    vm_dns     = string
    memory     = number
    cores      = number
  }))
}

variable "immich" {
  description = "Immich photo LXC on node pve2"
  type = object({
    vm_id            = number
    node_name        = string
    hostname         = string
    template_url     = string
    ip               = string
    gateway          = string
    memory           = number
    swap             = number
    cores            = number
    disk_size        = number
    photos_datastore = string
    photos_size      = number
    photos_path      = string
  })
}
