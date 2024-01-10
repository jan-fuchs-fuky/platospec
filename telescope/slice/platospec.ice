/*
 * Author: Jan Fuchs <fuky@asu.cas.cz>
 *
 * Copyright (C) 2022 Astronomical Institute; Academy Sciences of the Czech Republic; v.v.i.
 *
 * This file is part of PLATOSpec (ground based support of space missions PLATO
 * and TESS - new Czech spectrograph in collaboration with European Southern
 * Observatory).
 *
 *  $ slice2py --underscore --output-dir ./python slice/platospec.ice
 */

module PlatoSpec
{
    struct TelescopeGlobalState {
        int telescope;
        int dome;
        int slit;
        int mirror_cover;
        int focus;
        int status_bits;
        int error_bits;
    };

    struct TelescopeOffsets {
        double ra;
        double dec;
    };

    struct TelescopeUserSpeeds {
        double ra;
        double dec;
        int active;
    };

    struct TelescopeCoordinates {
        string ra;
        string dec;
        int position;
    };

    struct TelescopeMechanicalCoordinates {
        string ha;
        string da;
    };

    struct TelescopeMeteoStatus {
        int humidity;
        int precipitation;
        int status_word;
        int meteo_alarms;
        int wind_direction;
        double wind_speed;
        double brightness_east;
        double brightness_north;
        double brightness_west;
        double brightness_south;
        double brightness_max;
        double temperature;
        double atmospheric_pressure;
        double pyrgeometer;
    };

    struct TelescopeStatus {
        double utc;                          // GLUT
        double speed1;                       // TRS1
        double speed2;                       // TRS2
        double speed3;                       // TRS3
        double dec_screw_limit;              // TRSD
        double dome_position;                // DOPO
        double focus_position;               // FOPO
        int correction_model;                // TRCM
        TelescopeGlobalState global_state;   // GLST
        TelescopeOffsets user_offsets;       // TRUO
        TelescopeOffsets autoguider_offsets; // TRGO
        TelescopeUserSpeeds user_speeds;     // TRUS
        TelescopeCoordinates coordinates;    // TRRD
        TelescopeCoordinates setpoint;       // TRSP
        TelescopeMechanicalCoordinates axes; // TRHD
        TelescopeMeteoStatus meteo_status;   // MEST
    };

    interface Telescope
    {
        string run_ascol(string s);
        TelescopeStatus get_status();
    };
};
