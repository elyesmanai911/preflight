# Ansible: configuring the demo VM

Terraform (`infra/demo`) creates the VM. Ansible configures it and keeps it configured.

| Role | What it does |
|---|---|
| `hardening` | SSH: keys only, `preflight` user only, no root. Firewall (ufw): deny inbound except 22 and 80, plus the k3s pod and service networks. Security updates install daily, without automatic reboots. |

More roles (k3s, platform, secrets) and day-2 playbooks follow in the next PRs.

## Test locally (no Azure needed)

```bash
pip install ansible-core ansible-lint molecule "molecule-plugins[docker]"
ansible-galaxy collection install -r requirements.yml -p collections
ansible-lint
cd roles/hardening && ANSIBLE_COLLECTIONS_PATH=$PWD/../../collections molecule test
```

Molecule builds an Ubuntu 24.04 container with systemd, applies the role, applies it a second
time to prove nothing changes (idempotence), then checks the state that is actually in effect:
`sshd -T`, `ufw status`, `apt-config dump`. CI runs the same steps on every PR.
