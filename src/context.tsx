import React, { createContext, useEffect, useReducer } from 'react';
import { ActionsUnion, createAction, createActionPayload } from './actions';
import { Activity, Api, Event } from './api';

export enum ConnectionStatus {
    DISCONNECTED,
    CONNECTING,
    CONNECTED
}

interface State {
    currentApp: Activity | null;
    connectionStatus: ConnectionStatus;
    runningApps: Activity[];
    isAutoStartEnabled: boolean;
}

const DEFAULT_STATE: State = {
    currentApp: null,
    connectionStatus: ConnectionStatus.DISCONNECTED,
    runningApps: [],
    isAutoStartEnabled: false
};

export const ACTION_CHANGE_RUNNING_APP = 'action:change-running-app';
export const ACTION_CONNECT = 'action:connect';
export const ACTION_SET_CONNECTION_STATUS = 'action:set-connection-status';
export const ACTION_SET_RUNNING_APP = 'action:set-running-app';
export const ACTION_UPDATE_APPS = 'action:update-apps';
export const ACTION_LAUNCH_DISCORD = 'action:launch-discord';
export const ACTION_SET_AUTO_START_DISCORD = 'action:set-auto-start-discord';
export const ACTION_FETCH_SETTINGS = 'action:fetch-settings';

export const Actions = {
    changeRunningApp: createActionPayload<typeof ACTION_CHANGE_RUNNING_APP, Activity | null>(
        ACTION_CHANGE_RUNNING_APP
    ),
    connect: createAction<typeof ACTION_CONNECT>(ACTION_CONNECT),
    setConnectionStatus: createActionPayload<typeof ACTION_SET_CONNECTION_STATUS, ConnectionStatus>(
        ACTION_SET_CONNECTION_STATUS
    ),
    setRunningApp: createActionPayload<typeof ACTION_SET_RUNNING_APP, Activity | null>(
        ACTION_SET_RUNNING_APP
    ),
    updateApps: createActionPayload<typeof ACTION_UPDATE_APPS, Activity[]>(ACTION_UPDATE_APPS),
    launchDiscord: createAction<typeof ACTION_LAUNCH_DISCORD>(ACTION_LAUNCH_DISCORD),
    setAutoStartDiscord: createActionPayload<typeof ACTION_SET_AUTO_START_DISCORD, boolean>(ACTION_SET_AUTO_START_DISCORD),
    fetchSettings: createAction<typeof ACTION_FETCH_SETTINGS>(ACTION_FETCH_SETTINGS)
};

export type AcceptedActions = ActionsUnion<typeof Actions>;

const Context = createContext<[State, React.Dispatch<AcceptedActions>]>([
    DEFAULT_STATE,
    () => {
        /* noop */
    }
]);

function reducer(state: State, action: AcceptedActions): State {
    switch (action.type) {
        case ACTION_SET_CONNECTION_STATUS:
            return {
                ...state,
                connectionStatus: action.payload
            };
        case ACTION_SET_RUNNING_APP:
            return {
                ...state,
                currentApp: action.payload
            };
        case ACTION_UPDATE_APPS:
            return {
                ...state,
                runningApps: action.payload
            };
        case ACTION_SET_AUTO_START_DISCORD:
            return {
                ...state,
                isAutoStartEnabled: action.payload
            };
        default:
            return state;
    }
}

function enhancedDispatch(api: Api, dispatch: React.Dispatch<AcceptedActions>) {
    return async (action: AcceptedActions) => {
        switch (action.type) {
            case ACTION_CHANGE_RUNNING_APP:
                await api.updateActivity(action.payload);
                break;
            case ACTION_CONNECT:
                dispatch(Actions.setConnectionStatus(ConnectionStatus.CONNECTING));

                const status = await api.checkConnection();

                dispatch(
                    Actions.setConnectionStatus(
                        status ? ConnectionStatus.CONNECTED : ConnectionStatus.DISCONNECTED
                    )
                );

                break;
            case ACTION_LAUNCH_DISCORD:
                await api.launchDiscord();
                break;
            case ACTION_SET_AUTO_START_DISCORD:
                await api.setAutoStartDiscord(action.payload);
                dispatch(action);
                break;
            case ACTION_FETCH_SETTINGS:
                const isAutoStartDiscordEnabled = await api.isAutoStartDiscordEnabled();
                dispatch(Actions.setAutoStartDiscord(isAutoStartDiscordEnabled));
            default:
                dispatch(action);
                break;
        }
    };
}

interface ProviderProps {
    api: Api;
}

const Provider: React.FC<ProviderProps> = (props) => {
    const [state, baseDispatch] = useReducer(reducer, DEFAULT_STATE);
    
    const dispatch = enhancedDispatch(props.api, baseDispatch);
    dispatch(Actions.fetchSettings());
    
    useEffect(() => {
        const cb = () => {
            if (props.api.runningActivity) {
                dispatch(Actions.setRunningApp(props.api.runningActivity));
            }
        };

        window.addEventListener('online', cb);

        return () => {
            window.removeEventListener('online', cb);
        };
    }, [props.api]);

    useEffect(() => {
        props.api
            .on(Event.connect, () =>
                dispatch(Actions.setConnectionStatus(ConnectionStatus.CONNECTED))
            )
            .on(Event.disconnect, () =>
                dispatch(Actions.setConnectionStatus(ConnectionStatus.DISCONNECTED))
            )
            .on(Event.connecting, () =>
                dispatch(Actions.setConnectionStatus(ConnectionStatus.CONNECTING))
            )
            .on(Event.update, () => {
                dispatch(Actions.updateApps(Object.values(props.api.activities)));
                dispatch(Actions.setRunningApp(props.api.runningActivity));
            });

        dispatch(
            Actions.setConnectionStatus(
                props.api.connected ? ConnectionStatus.CONNECTED : ConnectionStatus.DISCONNECTED
            )
        );

        dispatch(Actions.updateApps(Object.values(props.api.activities)));
        dispatch(Actions.setRunningApp(props.api.runningActivity));

        if (!props.api.connected) {
            dispatch(Actions.connect());
        }

        return () => {
            props.api.removeAllListeners();
        };
    }, [props.api]);

    return <Context.Provider value={[state, dispatch]}>{props.children}</Context.Provider>;
};

export { Context, Provider };
