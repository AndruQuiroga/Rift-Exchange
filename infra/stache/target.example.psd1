# Copy to target.local.psd1 and fill using private infrastructure documentation.
# The local file is ignored by Git. Never commit real target inventory.
@{
    SshTarget = 'your-manager-alias'
    ExpectedHost = 'your-data-node'
    ExpectedUser = 'your-deploy-user'
    ExpectedSwarmId = 'your-verified-cluster-id'
    DataNode = 'your-data-node'
    BackupNode = 'your-separate-backup-node'
    BackupSshTarget = 'your-backup-alias'
    IngressNetwork = 'your-ingress-overlay'
    IngressOrigin = 'http://your-private-ingress'
}
