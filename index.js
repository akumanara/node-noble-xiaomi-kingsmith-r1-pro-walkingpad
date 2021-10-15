var async = require('async');
var noble = require('noble');

let minimalCommandSpace = 500;
let previousCommandTime = 0;
let pauseStats = false;
let peripheralIdOrAddress = '574c4d191bfc';

let char1 = null;
let char2 = null;

let meterObjects = [];
let timeObjects = [];
let speed, distance, timeInSeconds;

let serviceUUID = 'fe00';
// commands
let commands = {
  // startBelt: [0xf7, 0xa2, 0x04, 0x01, 0xa7, 0xfd], // working
  startBelt: [247, 162, 4, 1, 0xff, 253],
  changeSpeed0: [247, 162, 1, 0, 0xff, 253],
  changeSpeed60: [247, 162, 1, 60, 0xff, 253],
  changeSpeed80: [247, 162, 1, 80, 0xff, 253],
  changeSpeed30: [247, 162, 1, 30, 0xff, 253],
  askStats: [247, 162, 0, 0, 162, 253],
};
const reducer = (previousValue, currentValue) => previousValue + currentValue;

let fixCRC = function (array) {
  // cmd[-2] = sum(cmd[1:-2]) % 256
  let sum = 0;
  for (let i = 1; i < array.length - 2; i++) {
    sum += array[i];
  }
  let crc = sum % 256;
  array[array.length - 2] = crc;
};

// fixCRC(commands.startBelt);
noble.on('stateChange', function (state) {
  if (state === 'poweredOn') {
    //
    // Once the BLE radio has been powered on, it is possible
    // to begin scanning for services. Pass an empty array to
    // scan for all services (uses more time and power).
    //
    console.log('scanning...');
    noble.startScanning([serviceUUID], false);
  } else {
    noble.stopScanning();
  }
});

noble.on('discover', function (peripheral) {
  // we found a peripheral, stop scanning
  noble.stopScanning();

  //
  // The advertisment data contains a name, power level (if available),
  // certain advertised service uuids, as well as manufacturer data,
  // which could be formatted as an iBeacon.
  //
  //
  // Once the peripheral has been discovered, then connect to it.
  //
  peripheral.connect(function (err) {
    //
    // Once the peripheral has been connected, then discover the
    // services and characteristics of interest.
    //
    peripheral.discoverServices([serviceUUID], function (err, services) {
      services.forEach(function (service) {
        //
        // This must be the service we were looking for.
        //
        console.log('found service:', service.uuid);

        //
        // So, discover its characteristics.
        //
        service.discoverCharacteristics([], function (err, characteristics) {
          characteristics.forEach(function (characteristic) {
            //
            // Loop through each characteristic and match them to the
            // UUIDs that we know about.
            //
            console.log('found characteristic:', characteristic.uuid);

            // save the charaaacteristics
            if (characteristic.uuid == 'fe01') {
              char1 = characteristic;
            }

            if (characteristic.uuid == 'fe02') {
              char2 = characteristic;
            }
          });

          // Check to see if we found all of our characteristics.
          if (char1 && char2) {
            //
            // We did, so run the program!
            //
            program();
          } else {
            console.log('missing characteristics');
          }
        });
      });
    });
  });
});

async function sendCommand(cmd) {
  fixCRC(cmd);
  var dif = new Date().getTime() - previousCommandTime;
  console.log(dif);
  if (dif < minimalCommandSpace) {
    await sleep(minimalCommandSpace - dif);
  }

  sendCommandRaw(cmd);
}

function sendCommandRaw(cmd) {
  previousCommandTime = new Date().getTime();
  var tmpBuf = new Buffer.from(cmd);
  char2.write(tmpBuf, false, function (err) {
    // console.log('sendCommandRaw: ' + cmd);
    // console.log(err);
  });
}

let program = async function () {
  console.log(char1);

  char1.on('read', function (data, isNotification) {
    decodeStats(data);
  });

  char1.subscribe(function (err) {});

  // Asking for stats
  setInterval(askForStats, 1500);
  myCourse();
};

// Ez course 1km, ~12 mins
let myCourse = async () => {
  // Get ready
  await sleep(5000);

  // Start belt (wait 5 seconds until the belt is started (3... 2... 1...))
  sendCommand(commands.startBelt);
  await sleep(5000);

  // Set speed to 4km/h
  setSpeed(40);
  // Wait until we hit the 200 meters
  await meters(20);
  // Set speed to 5km/h
  setSpeed(50);
  // Wait until we hit the 600 meters
  await meters(60);
  // Set speed to 6km/h
  setSpeed(60);
  // Wait until we hit the 1000 meters
  await meters(100);
  // Set speed to 0km/h
  setSpeed(0);
};

function setSpeed(speed) {
  let speedCmd = [247, 162, 1, speed, 0xff, 253];
  sendCommand(speedCmd);
}

async function meters(value) {
  let promiseResolve;
  let prom = new Promise((resolve) => {
    promiseResolve = resolve;
  });
  let metersObj = {
    meters: value,
    promise: prom,
    resolver: promiseResolve,
  };
  meterObjects.push(metersObj);
  return metersObj.promise;
}

async function timers(value) {
  let promiseResolve;
  let prom = new Promise((resolve) => {
    promiseResolve = resolve;
  });
  let timersObj = {
    time: value,
    promise: prom,
    resolver: promiseResolve,
  };
  timeObjects.push(timersObj);
  return timersObj.promise;
}

function askForStats() {
  if (pauseStats) return;
  sendCommand(commands.askStats);
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

let decodeStats = function (data) {
  if (data[0] === 0xf8 && data[1] === 0xa2) {
    speed = data[3];
    distance = data.readUIntBE(8, 3);
    timeInSeconds = data.readUIntBE(5, 3);

    console.log(`speed: ${speed}`);
    console.log(`distance: ${distance}`);
    console.log(`timeInSeconds: ${timeInSeconds}`);

    // Check for meter objects
    meterObjects.forEach((meterObject) => {
      if (distance >= meterObject.meters) {
        console.log(`promises complete====================================`);
        meterObject.resolver();
        meterObjects = meterObjects.filter((item) => item !== meterObject);
      }
    });
    timeObjects.forEach((timeObj) => {
      if (timeInSeconds >= timeObj.time) {
        console.log(`promises complete====================================`);
        timeObj.resolver();
        timeObjects = timeObjects.filter((item) => item !== timeObj);
      }
    });
  } else {
  }
};
