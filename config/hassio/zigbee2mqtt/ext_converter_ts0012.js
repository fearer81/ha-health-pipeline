const {} = require('zigbee-herdsman-converters/lib/modernExtend');
const fz = require('zigbee-herdsman-converters/converters/fromZigbee');
const tz = require('zigbee-herdsman-converters/converters/toZigbee');
const exposes = require('zigbee-herdsman-converters/lib/exposes');
const reporting = require('zigbee-herdsman-converters/lib/reporting');
const ota = require('zigbee-herdsman-converters/lib/ota');
const utils = require('zigbee-herdsman-converters/lib/utils');
const globalStore = require('zigbee-herdsman-converters/lib/store');
const tuya = require('zigbee-herdsman-converters/lib/tuya');
const e = exposes.presets;
const ea = exposes.access;

const definition = {
    fingerprint: [{modelID: 'TS0012', manufacturerName: '_TZ3000_ewtuosug'}],
    model: 'TS0012',
    vendor: 'Avatto',
    description: 'Smart light switch - 2 gang without neutral wire',
    extend: tuya.extend.switch({switchType: true, backlightMode: true, endpoints: ['left', 'right']}),
    exposes: [e.switch().withEndpoint('left'), e.switch().withEndpoint('right'), 
      exposes.enum('power_on_behavior', ea.ALL, Object.values(tuya.moesSwitch.powerOnBehavior)),
      exposes.enum('backlight_mode', ea.ALL, ['low', 'medium', 'high']).withDescription('Indicator light status: LOW: Off | MEDIUM: On| HIGH: Inverted')],
    endpoint: (device) => {
        return {'left': 1, 'right': 2};
    },
    whiteLabel: [{vendor: 'TUYATEC', model: 'GDKES-02TZXD'}],
    meta: {multiEndpoint: true},
    configure: async (device, coordinatorEndpoint, logger) => {
        await device.getEndpoint(1).read('genBasic', ['manufacturerName', 'zclVersion', 'appVersion', 'modelId', 'powerSource', 0xfffe]);
        try {
            for (const ID of [1, 2]) {
                const endpoint = device.getEndpoint(ID);
                await reporting.bind(endpoint, coordinatorEndpoint, ['genOnOff']);
            }
        } catch (e) {
            // Fails for some: https://github.com/Koenkk/zigbee2mqtt/issues/4872
        }
        device.powerSource = 'Mains (single phase)';
        device.save();  
    },
};

module.exports = definition;