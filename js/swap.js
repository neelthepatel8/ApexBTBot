import { Connection, Keypair, VersionedTransaction } from "@solana/web3.js";
import fetch from "cross-fetch";
import { Wallet } from "@project-serum/anchor";
import yargs from 'yargs';
import { hideBin } from 'yargs/helpers';

const argv = yargs(hideBin(process.argv))
    .option('rpc', {
        type: 'string',
        default: 'https://mainnet.helius-rpc.com/?api-key=d8965fa9-a70f-4b56-a16f-ee72dc18bd4f'
    })
    .option('private-key', {
        type: 'string',
        required: true
    })
    .option('input-mint', {
        type: 'string',
        default: 'So11111111111111111111111111111111111111112'
    })
    .option('output-mint', {
        type: 'string',
        default: 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
    })
    .option('amount', {
        type: 'number',
        default: 1000000
    })
    .option('slippage', {
        type: 'number',
        default: 200
    })
    .argv;

const connection = new Connection(argv.rpc, 'confirmed');
console.log("private key is:::::::")
console.log(argv["private_key"])
const wallet = new Wallet(
    Keypair.fromSecretKey(
        Buffer.from(argv['private-key'], "base64")
    )
);

const quoteResponse = await (
    await fetch(
        `https://quote-api.jup.ag/v6/quote?inputMint=${argv['input-mint']}&outputMint=${argv['output-mint']}&amount=${argv.amount}&slippageBps=${argv.slippage}`
    )
).json();
console.log("Quote Recieved");

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
console.log("Tx built");
transaction.sign([wallet.payer]);

const { blockhash, lastValidBlockHeight } = await connection.getLatestBlockhash('confirmed');
// console.log("Latest blockhash: " + blockhash);

const rawTransaction = transaction.serialize();
console.log("Raw Tx built.");

const txid = await connection.sendRawTransaction(rawTransaction, {
    skipPreflight: true,
    maxRetries: 4,
    preflightCommitment: 'confirmed'
});
console.log("Txid: " + txid);

await connection.confirmTransaction({
    blockhash,
    lastValidBlockHeight,
    signature: txid,
},
"confirmed"
);
console.log("Tx confirmed!")
// console.log(`https://solscan.io/tx/${txid}`);