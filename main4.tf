terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.66.0"
    }
  }
}

provider "proxmox" {
  endpoint  = "https://192.168.1.200:8006/api2/json"
  api_token = "terraform@pve!terraform=fa7fd004-08a8-4367-8963-6e3fa28e3a79"
  insecure  = true
}

resource "proxmox_virtual_environment_vm" "lab_vm" {
  count = 10

  # 1. บังคับให้สร้างทีละเครื่องเพื่อลดคอขวด (Parallelism Control)
  # วิธีการคือใช้การตั้งค่าใน lifecycle หรือใช้คำสั่งตอน run (ดูหมายเหตุด้านล่าง)

  # 2. ตั้ง VM ID ให้เริ่มที่ 200
  vm_id = 200 + count.index

  name      = "lab-vm-${count.index}"
  node_name = "pve"

  clone {
    vm_id = 8000
  }

  cpu {
    cores = 2
  }

  memory {
    dedicated = 2048
  }

  network_device {
    bridge = "vmbr0"
  }

  initialization {
    ip_config {
      ipv4 {
        # 3. Fix IP 192.168.1.120 - 130
        # ใช้สูตร 120 + count.index
        address = "192.168.1.${120 + count.index}/24"
        gateway = "192.168.1.1"
      }
    }
  }
}
