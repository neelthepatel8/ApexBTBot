import { Connection, Keypair, VersionedTransaction } from "@solana/web3.js";
import fetch from "cross-fetch";
import { Wallet } from "@project-serum/anchor";

const connection = new Connection(
  "https://mainnet.helius-rpc.com/?api-key=d8965fa9-a70f-4b56-a16f-ee72dc18bd4f",
  'confirmed'
);
const wallet = new Wallet(
  Keypair.fromSecretKey(
    Buffer.from(
      "yG45Rz7SLtG/IIxK5CXl3OkNNspBSuUs3YifrTjDiDZLTaiaCUkLKmyG8UwWzqCS2n/wp7+Ljc/4/kA0F67XTA==",
      "base64"
    )
  )
);
const quoteResponse = await (
  await fetch(
    "https://quote-api.jup.ag/v6/quote?inputMint=So11111111111111111111111111111111111111112&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000&slippageBps=50"
  )
).json();
console.log({ quoteResponse });
const { swapTransaction } = await (
  await fetch("https://quote-api.jup.ag/v6/swap", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      quoteResponse,
      userPublicKey: wallet.publicKey.toString(),
      wrapAndUnwrapSol: true,
      dynamicComputeUnitLimit: true, 
      prioritizationFeeLamports: 'auto' 
    }),
  })
).json();
const swapTransactionBuf = Buffer.from(swapTransaction, "base64");
var transaction = VersionedTransaction.deserialize(swapTransactionBuf);
console.log(transaction);

transaction.sign([wallet.payer]);
const { blockhash, lastValidBlockHeight } = await connection.getLatestBlockhash('confirmed');

console.log("Latest blockhash: " + blockhash)
const rawTransaction = transaction.serialize();

console.log("Raw Tx: " + rawTransaction)

const txid = await connection.sendRawTransaction(rawTransaction, {
  skipPreflight: true,
  maxRetries: 3,
  preflightCommitment: 'confirmed'
});

console.log("Txid: " + txid)
await connection.confirmTransaction({
  blockhash,
  lastValidBlockHeight,
  signature: txid,
},
"confirmed"
);
console.log(`https://solscan.io/tx/${txid}`);