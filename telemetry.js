const koffi = require('koffi');

const kernel32 = koffi.load('kernel32.dll');
const msvcrt = koffi.load('msvcrt.dll');

const OpenFileMappingA = kernel32.func('void* __stdcall OpenFileMappingA(uint32_t, int, const char*)');
const MapViewOfFile = kernel32.func('void* __stdcall MapViewOfFile(void*, uint32_t, uint32_t, uint32_t, uintptr_t)');
const UnmapViewOfFile = kernel32.func('int __stdcall UnmapViewOfFile(void*)');
const CloseHandle = kernel32.func('int __stdcall CloseHandle(void*)');
const memcpy = msvcrt.func('void* __cdecl memcpy(_Out_ uint8_t*, _In_ void*, uintptr_t)');

const FILE_MAP_READ = 0x4;
const BUFFER_SIZE = 0x8000;

let handle = null, view = null;
let eventHistory = {
  jobFinished: { value: 0, timestamp: null, lastTriggered: null },
  pedagio: { value: 0, timestamp: null, lastTriggered: null }
};
let prevOdometer = null, prevFuel = null, totalFuelUsed = 0, totalDistanceKm = 0;

function connect() {
  if (view) return true;
  handle = OpenFileMappingA(FILE_MAP_READ, 0, "Local\\SCSTelemetry");
  if (!handle) return false;
  view = MapViewOfFile(handle, FILE_MAP_READ, 0, 0, BUFFER_SIZE);
  if (!view) {
    CloseHandle(handle);
    handle = null;
    return false;
  }
  return true;
}

function readBuffer() {
  if (!view) return null;
  const buffer = Buffer.alloc(BUFFER_SIZE);
  memcpy(buffer, view, BUFFER_SIZE);
  return buffer;
}

function getData() {
  if (!connect()) return null;
  const buf = readBuffer();
  if (!buf) return null;

  const extractString = (offset) => {
    const slice = buf.slice(offset, offset + 64);
    const nullIdx = slice.indexOf(0x0);
    return slice.toString('utf8', 0, nullIdx >= 0 ? nullIdx : 64).trim();
  };

  const gameTime = buf.readUInt32LE(0x40); // time_abs em MINUTOS
  const minutesInDay = gameTime % (24 * 60);
  const hours = Math.floor(minutesInDay / 60);
  const minutes = minutesInDay % 60;
  const time = String(hours).padStart(2, '0') + ':' + String(minutes).padStart(2, '0');

  const dayOfWeek = Math.floor(gameTime / (24 * 60)) % 7;
  const dayNames = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];
  const gameDate = dayNames[dayOfWeek];

  const speedMs = buf.readFloatLE(0x3b4);
  const speed = Math.round(speedMs * 3.6);
  const speedLimitRaw = buf.readFloatLE(0x42c);
  const speedLimit = speedLimitRaw > 0 ? Math.round(speedLimitRaw * 3.6) : null;
  const rpm = Math.round(buf.readFloatLE(0x3b8));
  const rpmMax = Math.round(buf.readFloatLE(0x2e4));
  const gear = buf.readInt32LE(0x1f8);
  const cruiseControl = Math.round(buf.readFloatLE(0x3dc) * 3.6);

  const fuelRaw = buf.readFloatLE(0x3e8);
  const fuel = Math.round(fuelRaw);
  const fuelCapacity = Math.round(buf.readFloatLE(0x2c0));
  const fuelRange = Math.round(buf.readFloatLE(0x3f0));

  const odometerRaw = buf.readFloatLE(0x420);
  if (prevOdometer !== null && prevFuel !== null) {
    const distDelta = odometerRaw - prevOdometer;
    const fuelDelta = prevFuel - fuelRaw;
    if (fuelDelta < -0.5) {
      totalDistanceKm = 0;
      totalFuelUsed = 0;
    } else if (distDelta > 0 && distDelta < 10 && fuelDelta > 0) {
      totalDistanceKm += distDelta;
      totalFuelUsed += fuelDelta;
    }
  }
  prevOdometer = odometerRaw;
  prevFuel = fuelRaw;

  const fuelAvgConsumption = totalFuelUsed > 0 && totalDistanceKm > 0
    ? Number((totalFuelUsed / totalDistanceKm).toFixed(2))
    : null;

  const routeDistance = buf.readFloatLE(0x424);
  const routeTime = buf.readFloatLE(0x428);
  const plannedDistanceKm = Math.round(buf.readUInt32LE(0x64));

  let routeTimeStr = null;
  if (routeTime > 0) {
    const h = Math.floor(routeTime / 3600);
    const m = Math.floor((routeTime % 3600) / 60);
    routeTimeStr = h > 0 ? h + 'h' + String(m).padStart(2, '0') : m + 'min';
  }

  const truckBrand = extractString(0x93c);
  const truckName = extractString(0x9bc);
  const cargo = extractString(0xa3c);
  const cityDst = extractString(0xabc);
  const compDst = extractString(0xb3c);
  const citySrc = extractString(0xbbc);
  const compSrc = extractString(0xc3c);
  const truckLicensePlate = extractString(0xc8c);
  const truckLicensePlateCountry = extractString(0xd0c);

  const odometer = Math.round(buf.readFloatLE(0x420));
  const wearEngine = Math.round(buf.readFloatLE(0x40c) * 100);
  const wearTransmission = Math.round(buf.readFloatLE(0x410) * 100);
  const wearCabin = Math.round(buf.readFloatLE(0x414) * 100);
  const wearChassis = Math.round(buf.readFloatLE(0x418) * 100);
  const wearWheels = Math.round(buf.readFloatLE(0x41c) * 100);
  const cargoDamage = Math.round(buf.readFloatLE(0x5bc) * 100);

  const jobIncome = Number(buf.readInt32LE(0xfa0));
  const jobCancelledPenalty = Number(buf.readInt32LE(0x1068));
  const jobDeliveredRevenue = Number(buf.readInt32LE(0x1070));
  const fineAmount = Number(buf.readBigInt64LE(0x1078));
  const tollgatePayAmount = Number(buf.readBigInt64LE(0x1080));
  const ferryPayAmount = Number(buf.readBigInt64LE(0x1088));
  const trainPayAmount = Number(buf.readBigInt64LE(0x1090));

  const onJob = buf.readUInt8(0x10cc);
  const jobFinished = buf.readUInt8(0x10cd);
  const jobCancelled = buf.readUInt8(0x10ce);
  const jobDelivered = buf.readUInt8(0x10cf);
  const fined = buf.readUInt8(0x10d0);
  const tollgate = buf.readUInt8(0x10d1);
  const ferry = buf.readUInt8(0x10d2);
  const train = buf.readUInt8(0x10d3);
  const refuel = buf.readUInt8(0x10d4);
  const refuelPayed = buf.readUInt8(0x10d5);

  const refuelAmount = buf.readFloatLE(0x5b8);

  const jobDeliveredDistanceKm = Math.abs(buf.readFloatLE(0x5b4));
  const jobDeliveredEarnedXp = buf.readInt32LE(0x280);

  return {
    time, gameDate, speed, speedLimit, rpm, rpmMax, gear, cruiseControl,
    fuel, fuelCapacity, fuelAvgConsumption, fuelRange,
    routeDistance: Math.round(routeDistance / 1000), routeTime: routeTimeStr, plannedDistanceKm,
    truckBrand, truckName, cargo, cityDst, compDst, citySrc, compSrc,
    truckLicensePlate, truckLicensePlateCountry,
    odometer, cargoDamage,
    wearEngine, wearTransmission, wearCabin, wearChassis, wearWheels,
    jobIncome, jobCancelledPenalty, jobDeliveredRevenue,
    fineAmount, tollgatePayAmount, ferryPayAmount, trainPayAmount,
    onJob, jobFinished, jobCancelled, jobDelivered, fined, tollgate, ferry, train,
    refuel, refuelPayed, refuelAmount,
    jobDeliveredDistanceKm, jobDeliveredEarnedXp
  };
}

function detectEventTransitions(currentFlags) {
  const events = [];
  const now = Date.now();

  const anyPedagio = currentFlags.tollgate || currentFlags.ferry || currentFlags.train;
  const prevPedagio = eventHistory.pedagio.value;

  if (prevPedagio === 0 && anyPedagio === 1) {
    events.push({ event: 'pedagio', type: 'START', value: 1, timestamp: now });
    eventHistory.pedagio.lastTriggered = now;
  } else if (prevPedagio === 1 && anyPedagio === 0) {
    const dur = eventHistory.pedagio.lastTriggered ? now - eventHistory.pedagio.lastTriggered : null;
    events.push({ event: 'pedagio', type: 'END', value: 0, timestamp: now, duration: dur });
  }
  eventHistory.pedagio.value = anyPedagio;
  eventHistory.pedagio.timestamp = now;

  const jfCurr = currentFlags.jobFinished;
  const jfPrev = eventHistory.jobFinished.value;

  if (jfPrev === 0 && jfCurr === 1) {
    events.push({ event: 'jobFinished', type: 'START', value: jfCurr, timestamp: now });
    eventHistory.jobFinished.lastTriggered = now;
  } else if (jfPrev === 1 && jfCurr === 0) {
    const dur = eventHistory.jobFinished.lastTriggered ? now - eventHistory.jobFinished.lastTriggered : null;
    events.push({ event: 'jobFinished', type: 'END', value: jfCurr, timestamp: now, duration: dur });
  }
  eventHistory.jobFinished.value = jfCurr;
  eventHistory.jobFinished.timestamp = now;

  return events;
}

function startTelemetry(win) {
  let lastEventKey = null, lastEventTime = 0;
  const DEDUP_COOLDOWN = 5000;
  let startTime = Date.now();

  let intervalId = setInterval(() => {
    if (win.isDestroyed()) { clearInterval(intervalId); return; }

    const data = getData();
    if (!data) {
      win.webContents.send('telemetry', null);
      return;
    }

    const flags = {
      jobFinished: data.jobFinished,
      tollgate: data.tollgate,
      ferry: data.ferry,
      train: data.train
    };

    const transitions = detectEventTransitions(flags);
    const elapsed = Date.now() - startTime;

    if (transitions && transitions.length > 0) {
      if (elapsed > 3000) {
        const valid = transitions.filter(ev => {
          const key = ev.event + '-' + ev.type;
          const now = Date.now();
          if (key === lastEventKey && (now - lastEventTime) < DEDUP_COOLDOWN) return false;
          return true;
        });

        valid.forEach(ev => {
          const payload = { event: ev.event, type: ev.type, timestamp: ev.timestamp };
          if (ev.type === 'END') payload.duration = ev.duration;
          payload.telemetry = {
            citySrc: data.citySrc, cityDst: data.cityDst,
            cargo: data.cargo,
            truckBrand: data.truckBrand, truckName: data.truckName,
            truckLicensePlate: data.truckLicensePlate,
            truckLicensePlateCountry: data.truckLicensePlateCountry,
            tollgatePayAmount: data.tollgatePayAmount,
            ferryPayAmount: data.ferryPayAmount,
            trainPayAmount: data.trainPayAmount,
            jobDeliveredRevenue: data.jobDeliveredRevenue,
            jobIncome: data.jobIncome,
            jobDeliveredDistanceKm: data.jobDeliveredDistanceKm,
            jobDeliveredEarnedXp: data.jobDeliveredEarnedXp,
            plannedDistanceKm: data.plannedDistanceKm,
            cargoDamage: data.cargoDamage
          };
          lastEventKey = ev.event + '-' + ev.type;
          lastEventTime = Date.now();
          if (win && !win.isDestroyed() && win.webContents) {
            try { win.webContents.send('event-transition', payload); }
            catch (e) { /* send failed */ }
          }
        });
      }
    }

    const anyPedagio = !!(data.tollgate || data.ferry || data.train);

    win.webContents.send('telemetry', { ...data, anyPedagio });
  }, 100);
}

module.exports = startTelemetry;
