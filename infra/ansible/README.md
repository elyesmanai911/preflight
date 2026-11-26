# Ansible: configuring the demo VM

Terraform (`infra/demo`) creates the VM. Ansible configures it and keeps it configured.

| Role | What it does |
|---|---|
| `hardening` | SSH: keys only, `preflight` user only, no root. Firewall (ufw): deny inbound except 22 and 80, plus the k3s pod and service networks. Security updates install daily, without automatic reboots. |
| `k3s` | The pinned k3s release binary, verified against the release's checksum file, and its systemd unit. Waits for the node to be Ready. |
| `platform` | Argo CD (via k3s's Helm controller), the preview ApplicationSet on the VM's domain, Loki, Alloy and the triage watcher. |
| `secrets` | Reads the GitHub token and LLM key from Key Vault with the VM's managed identity and stores them as Kubernetes secrets. |

## Run it on the VM

`terraform apply` in `infra/demo` writes `inventory/demo.yml` (git-ignored), then:

```bash
ansible-playbook -i inventory/demo.yml site.yml
```

## Test locally (no Azure needed)

```bash
pip install ansible-core ansible-lint molecule "molecule-plugins[docker]"
ansible-galaxy collection install -r requirements.yml -p collections
ansible-lint
cd roles/hardening && ANSIBLE_COLLECTIONS_PATH=$PWD/../../collections molecule test && cd ../..
ANSIBLE_COLLECTIONS_PATH=$PWD/collections molecule test -s site   # the whole site.yml
```

Molecule builds an Ubuntu 24.04 container with systemd, applies the role, applies it a second
time to prove nothing changes (idempotence), then checks the state that is actually in effect:
`sshd -T`, `ufw status`, `apt-config dump`. The `site` scenario runs the real `site.yml` and
checks that the platform comes up: k3s version, Argo CD available, the ApplicationSet on the
right domain, the platform apps registered, and Traefik reachable on port 80 through the firewall.
Only `secrets` is skipped there, since it needs an Azure managed identity. CI runs the same steps on every PR.
