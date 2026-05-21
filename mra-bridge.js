// mra-bridge.js
// Converte dados de telemetria do Electron para o formato do ETS2 Telemetry Server
// e emula o Funbit.Ets.Telemetry.Dashboard para o dashboard.js funcionar

(function() {
  'use strict';

  window.Funbit = window.Funbit || {};
  window.Funbit.Ets = window.Funbit.Ets || {};
  window.Funbit.Ets.Telemetry = window.Funbit.Ets.Telemetry || {};

  var TelemetryDashboard = function() {
    this.filter = null;
    this.render = null;
    this.initialize = null;
  };

  Funbit.Ets.Telemetry.Dashboard = TelemetryDashboard;

  // Configuracao da skin (simula config.json do Telemetry Server)
  // name vazio = g_pathPrefix fica '' (arquivos na raiz do app)
  var skinConfig = {
    name: '',
    ets2: {
      mapPack: 'ets2',
      distanceUnits: 'km',
      weightUnits: 'kg',
      currencyCode: 'EUR'
    },
    ats: {
      mapPack: 'ats',
      distanceUnits: 'km',
      weightUnits: 'kg',
      currencyCode: 'USD'
    },
    language: 'en-US.json',
    timeFormat: '24h',
    checkForUpdates: false
  };

  // Traducoes minimas
  var translations = {
    LoadingMapPleaseWait: 'Loading map, please wait...',
    ETA: 'ETA',
    CurrentJob: 'Current Job',
    NoJob: 'No Job',
    NextRestStopIn: 'Next Rest Stop',
    CargoName: 'Cargo',
    Destination: 'Destination',
    Expected: 'Expected',
    JobIncome: 'Income',
    Remains: 'Remaining',
    Truck: 'Truck',
    Trailer: 'Trailer',
    MobileRouteAdvisor: 'Mobile Route Advisor',
    WorldOfTrucksContract: 'World of Trucks Contract',
    SundayAbbreviated: 'Sun',
    MondayAbbreviated: 'Mon',
    TuesdayAbbreviated: 'Tue',
    WednesdayAbbreviated: 'Wed',
    ThursdayAbbreviated: 'Thu',
    FridayAbbreviated: 'Fri',
    SaturdayAbbreviated: 'Sat',
    XMinutes: '{0} min',
    XMinute: '{0} min',
    XHours: '{0} h',
    XHour: '{0} h',
    XDays: '{0} d',
    XDay: '{0} d'
  };

  window.g_translations = translations;
  window.g_skinConfig = skinConfig;

  // Converte dados do Electron para o formato do Telemetry Server
  function electronToTelemetry(data) {
    if (!data) return null;

    var speedMs = (data.speed || 0) / 3.6;
    var speedLimitMs = data.speedLimit ? data.speedLimit / 3.6 : 0;

    // Converter wear de % (0-100) para 0-1
    var wearEngine = (data.wearEngine || 0) / 100;
    var wearTransmission = (data.wearTransmission || 0) / 100;
    var wearCabin = (data.wearCabin || 0) / 100;
    var wearChassis = (data.wearChassis || 0) / 100;
    var wearWheels = (data.wearWheels || 0) / 100;
    var trailerWear = (data.cargoDamage || 0) / 100;

    var gameMinutes = data.gameTimeAbsMinutes || 0;
    var gameTimeIso = '0001-01-01T' +
      String(Math.floor(gameMinutes / 60) % 24).padStart(2, '0') + ':' +
      String(gameMinutes % 60).padStart(2, '0') + ':00Z';

    // nextRestStopTime — usar um valor padrao
    var nextRest = '0001-01-01T11:00:00Z';

    // deadlineTime — usar um placeholder
    var deadlineTime = data.onJob ? '0001-01-02T00:00:00Z' : '0001-01-01T00:00:00Z';

    // estimatedTime em segundos
    var estSeconds = 0;
    if (data.routeTime) {
      var parts = data.routeTime.match(/(\d+)h(\d+)/);
      if (parts) {
        estSeconds = parseInt(parts[1]) * 3600 + parseInt(parts[2]) * 60;
      } else {
        var minMatch = data.routeTime.match(/(\d+)min/);
        if (minMatch) estSeconds = parseInt(minMatch[1]) * 60;
      }
    }

    // estimatedDistance em metros
    var estDistanceMeters = (data.routeDistance || 0) * 1000;

    // job remaining time
    var jobRemaining = data.onJob ? '0001-01-01T02:00:00Z' : '0001-01-01T00:00:00Z';

    var gameName = data.game || 'ETS2';
    var isAts = gameName === 'ATS';

    return {
      game: {
        connected: true,
        paused: false,
        gameName: gameName,
        time: gameTimeIso,
        timeScale: 19,
        nextRestStopTime: nextRest,
        version: '1.53',
        telemetryPluginVersion: '7'
      },
      truck: {
        id: 'player',
        make: data.truckBrand || '',
        model: data.truckName || '',
        speed: speedMs,
        cruiseControlOn: data.cruiseControl > 0,
        cruiseControlSpeed: data.cruiseControl > 0 ? (data.cruiseControl / 3.6) : 0,
        displayedGear: data.gear || 0,
        shifterType: 'arcade',
        fuel: data.fuel || 0,
        fuelCapacity: data.fuelCapacity || 1,
        fuelWarningFactor: 0.15,
        fuelWarningOn: data.fuelCapacity > 0 ? (data.fuel / data.fuelCapacity) < 0.15 : false,
        electricOn: true,
        engineOn: true,
        engineRpm: data.rpm || 0,
        engineRpmMax: data.rpmMax || 2500,
        forwardGears: 12,
        reverseGears: 2,
        retarderLevel: 0,
        brand: data.truckBrand || '',
        name: data.truckName || '',
        licensePlate: data.truckLicensePlate || '',
        licensePlateCountry: data.truckLicensePlateCountry || '',
        odometer: data.odometer || 0,
        wearEngine: wearEngine,
        wearTransmission: wearTransmission,
        wearCabin: wearCabin,
        wearChassis: wearChassis,
        wearWheels: wearWheels,
        placement: {
          x: data.truckX || 0,
          y: 0,
          z: data.truckZ || 0,
          heading: 0,
          pitch: 0,
          roll: 0
        }
      },
      trailer: {
        attached: !!data.onJob,
        id: '',
        name: data.cargo || '',
        wear: trailerWear,
        mass: (data.cargo || '').length > 0 ? 15000 : 0
      },
      cargo: {
        cargo: data.cargo || '',
        mass: 15000
      },
      job: {
        income: data.jobIncome || 0,
        deadlineTime: deadlineTime,
        remainingTime: jobRemaining,
        sourceCity: data.citySrc || '',
        destinationCity: data.cityDst || '',
        sourceCompany: '',
        destinationCompany: data.compDst || '',
        isSpecial: false
      },
      navigation: {
        speedLimit: speedLimitMs,
        estimatedTime: estSeconds,
        estimatedDistance: estDistanceMeters
      }
    };
  }

  // Instancia do prototipo do dashboard
  var dashboardProto = Funbit.Ets.Telemetry.Dashboard.prototype;

  // Escuta mensagens do parent (webview host)
  window.addEventListener('message', function(event) {
    if (!event.data) return;

    if (event.data.type === 'mra-config') {
      if (event.data.skinConfig) {
        skinConfig = event.data.skinConfig;
        window.g_skinConfig = skinConfig;
      }
      initDashboard();
      return;
    }

    if (event.data.type === 'mra-telemetry') {
      handleTelemetry(event.data.data);
      return;
    }
  });

  var dashboardInitialized = false;

  function initDashboard() {
    if (dashboardInitialized) return;

    // Forca aba do mapa
    try { localStorage.setItem('currentTab', '_map'); } catch(e) {}

    if (typeof dashboardProto.initialize === 'function') {
      dashboardProto.initialize(skinConfig);
    }
    // Corrige g_pathPrefix sobrescrito por initialize() — arquivos estao na raiz
    window.g_pathPrefix = '';

    // Mostra mapa assim que disponivel
    var _mapCheck = setInterval(function() {
      if (typeof g_map !== 'undefined' && g_map) {
        try { g_map.updateSize(); } catch(e) {}
        clearInterval(_mapCheck);
      }
    }, 200);
    setTimeout(function() { clearInterval(_mapCheck); }, 15000);

    dashboardInitialized = true;
  }

  function handleTelemetry(rawData) {
    var data = electronToTelemetry(rawData);
    if (!data) return;

    if (!dashboardInitialized) {
      initDashboard();
    }

    // Chama filter e render se estiverem definidos
    if (typeof dashboardProto.filter === 'function') {
      data = dashboardProto.filter(data);
    }
    if (data && typeof dashboardProto.render === 'function') {
      dashboardProto.render(data);
    }
  }

  // Expor funcao para ser chamada de fora
  window.mraBridge = {
    handleTelemetry: handleTelemetry,
    initDashboard: initDashboard,
    config: skinConfig
  };

  // Polyfill: $.getJSON usa XHR que falha com protocolo app:// no webview.
  // Substitui por fetch() que funciona corretamente.
  if (typeof $ !== 'undefined') {
    var _origGetJSON = $.getJSON;
    $.getJSON = function(url, success) {
      return fetch(url, { cache: 'no-cache' })
        .then(function(r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        })
        .then(function(data) {
          if (typeof success === 'function') success(data);
        })
        .catch(function(err) {
          console.warn('MRA: getJSON failed for', url, err);
        });
    };

    // Polyfill: $.getScript usa script tag injection (funciona cross-origin)
    var _origGetScript = $.getScript;
    $.getScript = function(url, success) {
      var script = document.createElement('script');
      script.src = url;
      script.onload = function() {
        if (typeof success === 'function') success();
        script.remove();
      };
      script.onerror = function() {
        script.remove();
        console.warn('MRA: getScript failed for', url);
      };
      document.head.appendChild(script);
    };
  }

  // Player icon fix: gera data URI via Canvas (evita problema de carregar PNG via app://)
  function _createPlayerDataUri() {
    var size = 64;
    var c = document.createElement('canvas');
    c.width = size;
    c.height = size;
    var ctx = c.getContext('2d');
    var cx = size / 2;
    var cy = size / 2;
    var r = size * 0.22;
    // Bolinha azul com borda branca
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = '#2979ff';
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 3;
    ctx.stroke();
    return c.toDataURL();
  }

  var _playerFixAttempts = 0;
  var _playerFixTimer = setInterval(function() {
    _playerFixAttempts++;
    if (typeof g_playerFeature !== 'undefined' && g_playerFeature && typeof ol !== 'undefined') {
      try {
        var dataUri = _createPlayerDataUri();
        var newIcon = new ol.style.Icon({ src: dataUri, scale: 0.8 });
        g_playerFeature.setStyle(new ol.style.Style({ image: newIcon }));
        // Atualiza referencia global para rotacao funcionar
        window.g_playerIcon = newIcon;
      } catch(e) {}
      clearInterval(_playerFixTimer);
    }
    if (_playerFixAttempts > 60) { clearInterval(_playerFixTimer); }
  }, 500);
})();
