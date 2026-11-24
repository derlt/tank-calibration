// Print a VAPID key pair (P-256) for the lock-screen alarms, base64url.
//   node scripts/make_vapid.mjs
// VAPID_PUBLIC_KEY is a plain variable; VAPID_PRIVATE_KEY is a Worker secret
// (never in git).  See docs/cloud.md, "Lock-screen alarms".
import { generateKeyPairSync } from "node:crypto";

const { publicKey, privateKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
const pub = publicKey.export({ format: "jwk" }), prv = privateKey.export({ format: "jwk" });
const raw = Buffer.concat([Buffer.from([4]), Buffer.from(pub.x, "base64url"), Buffer.from(pub.y, "base64url")]);
console.log(`VAPID_PUBLIC_KEY=${raw.toString("base64url")}`);
console.log(`VAPID_PRIVATE_KEY=${prv.d}`);
