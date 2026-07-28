const { build } = require("./package.json");

module.exports = {
  ...build,
  artifactName:
    "Jiaotang-Skills-Manager-${version}-unsigned-local-${os}-${arch}.${ext}",
  forceCodeSigning: false,
  mac: {
    ...build.mac,
    identity: null,
    hardenedRuntime: false,
    gatekeeperAssess: false,
  },
  win: {
    ...build.win,
    signExecutable: false,
    signAndEditExecutable: true,
    verifyUpdateCodeSignature: false,
  },
};
