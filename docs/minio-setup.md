# Cloud backup: MinIO setup

MedTracker's **☁ Back up** button uploads an encrypted copy of the database to MinIO.
This guide is for whoever runs the MinIO server and builds MedTracker releases.

## Addresses

| What | Address |
|---|---|
| S3 API (what MedTracker talks to) | `https://s3.kalourmade.com` |
| Web console (for people) | `https://minio.kalourmade.com` |
| Bucket | `medtracker-inventory` |

Both values are in `config.py` (`CLOUD_ENDPOINT`, `CLOUD_BUCKET`).

Each backup is stored as `<computer name>/medtracker_<YYYY-MM-DD_HHMMSS>.db.gz.enc`: gzip
compressed, then AES-256-GCM encrypted with the passphrase set on that PC
(**File → Cloud backup setup...**). Without the passphrase a backup cannot be read or restored.

## 1. Turn on versioning

A backup that is overwritten or deleted by mistake can then still be recovered.

```sh
mc alias set kalour https://s3.kalourmade.com <ADMIN_ACCESS_KEY> <ADMIN_SECRET_KEY>
mc version enable kalour/medtracker-inventory
```

## 2. Give MedTracker's key only what it needs

The access key and secret key are built into every installer, and anyone with an installer can
dig them out. So the key must be allowed to upload, list and download in this one bucket, and
nothing else: no deleting and no other buckets.

`medtracker-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": ["arn:aws:s3:::medtracker-inventory/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": ["arn:aws:s3:::medtracker-inventory"]
    }
  ]
}
```

```sh
mc admin policy create kalour medtracker-backup medtracker-policy.json
mc admin user add kalour <ACCESS_KEY> <SECRET_KEY>
mc admin policy attach kalour medtracker-backup --user <ACCESS_KEY>
```

The keys go in `.env` (`accesskey=...`, `secretkey=...`; git-ignored).

## 3. Optional: delete old backups automatically

```sh
mc ilm rule add kalour/medtracker-inventory --expire-days 365 --noncurrent-expire-days 30
```

## 4. Building releases with the keys

- **Locally:** `build.sh` / `build.bat` / `build-linux.sh` run `scripts/make_cloud_keys.py`, which
  reads `.env` and writes `cloud_keys.py` (git-ignored) into the build.
- **GitHub Actions:** add two repository secrets (Settings → Secrets and variables → Actions):
  `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY`, with the values from `.env`.

Before anything is built, the workflow checks the keys (`scripts/check_cloud_keys.py`): they
must be set and MinIO must accept them (one read-only request). A release (tag push) stops there
if they don't, with the reason in the log. A manual run from the Actions tab only warns about
missing keys. Local builds without keys still work; the button then says cloud backup is not
available.

## If a key leaks

1. Make a new key with the same policy (step 2) and remove the old one:
   `mc admin user remove kalour <OLD_ACCESS_KEY>`.
2. Put the new key in `.env` and the GitHub secrets.
3. Release a new MedTracker version. Older versions can no longer back up until they update.

The backups themselves stay safe: they are encrypted with each pharmacy's passphrase.
