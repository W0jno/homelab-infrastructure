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