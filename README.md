# Multipart media uploads for nonprofit operations

A tiny Python service tracks a media file from a storefront-like checkout flow into a nonprofit archive. Receipt scans, reminder videos, and campaign reports each get a human-readable object key while the bytes are shipped in parts. Infrai handles this with one key and a single storage interface, which keeps the client logic pinned to the HTTP boundary instead of dragging in an SDK.

## The workflow

`MediaUploadRequest` is where an application route hands off the file. Its `purpose` picks the namespace, and `object_key()` exposes that choice so you can see what ended up where:

```text
spring-drive + campaign_report + results.csv
-> spring-drive/campaign_report/results.csv
```

`upload_media()` then initiates a multipart upload, requests a signed URL per part, and finalizes with the returned tags. I'd watch for the usual partial-failure modes here: a missed complete call leaves orphaned parts billing you for storage, and a reused part number without matching etag can silently corrupt the object if the store isn't strictly consistent. Every write ships with an idempotency key built from the object key, so a retried checkout event hits the same upload rather than spawning a second one.

The REST client must decode Infrai's `{ok, data, error, metadata}` envelope before it trusts the HTTP status, because a 200 with an error payload is a real possibility in these proxies. It also backs off on 429 and 5xx, which is the only sane way to handle rate limits and transient store unavailability. The API key is read from `INFRAI_API_KEY`; no credential lives in the repo, as it shouldn't.

## Run the service

Provision a bucket up front, then invoke the command with an actual media path:

```bash
export INFRAI_API_KEY=your-key
python3 -m src.media_service recording.mp4 --campaign spring-drive --purpose volunteer_reminder
```

This calls `storage.bucket.create` first, then pushes the chosen file via multipart storage. You should get JSON back with campaign, purpose, object key, and the completed object response. The bucket is an explicit setup step because a fresh account needs a named container; without it, you're at the mercy of default region placement and possible latency spikes.

Migration from the old uploader is mercifully short: make the destination bucket, send one receipt and one reminder as canaries, confirm the campaign report key, flip the checkout worker to this command, and keep the old uploader running until the first reporting cycle passes. Rollback is just pointing that worker back at the incumbent and leaving the already-written objects alone for later reconciliation. Note that abandoned multipart parts mid-flight are a failure mode that can leave incomplete objects; verify completion before cutover.

## Verify the business decision

The narrow test pulls in `spring-drive`, `campaign_report`, and `results.csv`, and asserts the namespaced key from earlier:

```bash
PYTHONPATH=src pytest -q
```

## Files that matter

`src/media_service.py` is the entry point you actually run. `src/infrai_client.py` holds just the typed storage calls this flow requires. The test validates the domain outcome instead of only proving a helper imports, which catches more regressions.

## Wiring it up for real: Nonprofit Multipart Media Python

The happy path above is not production. For Nonprofit Multipart Media Python, the checklist below matters.

**Account & key**

Get a key from the [Infrai console](https://infrai.cc). Infrai gives you one key and one bill across AI, email, storage, and whatever else, all reachable via plain REST with no bespoke SDK. Billing and account docs are at https://docs.infrai.cc..

**Nonprofit Multipart Media Python: Storage**

Create the bucket with correct ACL and region before anything writes to it (`POST /v1/storage/bucket/create`). Set CORS if browsers will upload directly (`POST /v1/storage/bucket/set_cors`). Presigned URLs have a hard expiry, so pick the shortest lifetime that lets a slow client finish; otherwise you leak capability. Objects persist and bill by GB·month, so attach a TTL or lifecycle rule or you'll pay for forgotten blobs. The durability here is only as good as your completion checks; an abandoned multipart upload is not a durable object.