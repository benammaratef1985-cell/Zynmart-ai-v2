const StellarSDK = require("@stellar/stellar-sdk");

const server = new StellarSDK.Horizon.Server("https://api.testnet.minepi.com");

const address = process.env.PI_APP_PUBLIC_KEY;

if (!address) {
  console.error("PI_APP_PUBLIC_KEY غير مضبوط");
  process.exit(1);
}

server.loadAccount(address)
  .then(account => {
    console.log("PI TESTNET: OK");
    console.log("ADDRESS:", address);
    console.log("SEQUENCE:", account.sequenceNumber());
  })
  .catch(err => {
    console.error("PI TESTNET ERROR");
    console.error(err.response?.data || err.message || err);
    process.exit(1);
  });
