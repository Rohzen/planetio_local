odoo.define('planetio.DeforestationAnalysisDialog', function (require) {
    'use strict';

    const Dialog = require('web.Dialog');
    const FormController = require('web.FormController');
    const core = require('web.core');
    const pyUtils = require('web.py_utils');

    const qweb = core.qweb;
    const _t = core._t;

    function clamp(value, min, max) {
        return Math.min(max, Math.max(min, value));
    }

    function buildConfig(event) {
        let options = {};
        if (event.data.options && event.data.options.progress_window) {
            options = event.data.options.progress_window;
        } else if (event.data.attrs && event.data.attrs.options) {
            try {
                const parsed = pyUtils.py_eval(event.data.attrs.options);
                if (parsed && parsed.progress_window) {
                    options = parsed.progress_window;
                }
            } catch (err) {
                // ignore malformed options
            }
        }
        const closeDelay = Number(options.close_delay);
        const tickInterval = Number(options.tick_interval);
        const tickAmount = Number(options.tick_amount);
        return {
            title: options.title || _t('Deforestation analysis'),
            message: options.message || _t('The deforestation analysis is running. Please wait…'),
            successMessage: options.success_message || _t('Deforestation analysis completed.'),
            failureMessage: options.failure_message || _t('Deforestation analysis failed.'),
            closeDelay: Number.isFinite(closeDelay) ? closeDelay : 800,
            tickInterval: Number.isFinite(tickInterval) ? tickInterval : 1000,
            tickAmount: Number.isFinite(tickAmount) ? tickAmount : 8,
        };
    }

    function createDialog(controller, config) {
        const dialog = new Dialog(controller, {
            title: config.title,
            buttons: [],
            size: 'medium',
            $content: $(qweb.render('planetio.DeforestationProgressDialog', {
                message: config.message,
            })),
        });

        const $bar = dialog.$('.progress-bar');
        const $value = dialog.$('.planetio_progress_value');
        const $message = dialog.$('.planetio_progress_message');
        const $summary = dialog.$('.planetio_progress_summary');

        let currentValue = 0;

        const setProgress = function (value) {
            currentValue = clamp(Math.round(value), 0, 100);
            $bar.css('width', currentValue + '%');
            $bar.attr('aria-valuenow', currentValue);
            $value.text(currentValue + '%');
        };

        const setState = function (stateMessage, options) {
            if (stateMessage) {
                $message.text(stateMessage);
            }
            if (options && options.stateClass) {
                $bar.removeClass('bg-success bg-danger');
                if (options.stateClass) {
                    $bar.addClass(options.stateClass);
                }
            }
            if (options && options.striped !== undefined) {
                $bar.toggleClass('progress-bar-striped progress-bar-animated', options.striped);
            }
        };

        const setSummary = function (summary) {
            if (summary) {
                $summary.text(summary).removeClass('d-none');
            } else {
                $summary.addClass('d-none').text('');
            }
        };

        return {
            dialog: dialog,
            setProgress: setProgress,
            setState: setState,
            setSummary: setSummary,
            getProgress: function () {
                return currentValue;
            },
        };
    }

    function startTicker(api, config) {
        const interval = window.setInterval(function () {
            const nextValue = clamp(api.getProgress() + config.tickAmount, 0, 90);
            api.setProgress(nextValue);
        }, clamp(config.tickInterval, 200, 5000));
        return function stopTicker() {
            window.clearInterval(interval);
        };
    }

    function getSummary(controller) {
        if (!controller.model || !controller.handle) {
            return null;
        }
        const record = controller.model.get(controller.handle);
        if (!record || !record.data) {
            return null;
        }
        return record.data.deforestation_analysis_summary || null;
    }

    FormController.include({
        _onButtonClicked: function (event) {
            if (event.data && event.data.attrs && event.data.attrs.name === 'action_analyze_deforestation') {
                const config = buildConfig(event);
                const api = createDialog(this, config);
                api.dialog.open();
                api.setProgress(0);
                api.setState(config.message, { striped: true });
                const stopTicker = startTicker(api, config);

                const actionPromise = Promise.resolve(this._super.apply(this, arguments));

                const closeAfterDelay = () => {
                    return new Promise((resolve, reject) => {
                        window.setTimeout(() => {
                            try {
                                api.dialog.close();
                                resolve();
                            } catch (err) {
                                reject(err);
                            }
                        }, clamp(config.closeDelay, 0, 10000));
                    });
                };

                return actionPromise.then((result) => {
                    stopTicker();
                    const reloadPromise = this.reload();
                    const finalize = () => {
                        api.setProgress(100);
                        api.setState(config.successMessage, { striped: false, stateClass: 'bg-success' });
                        const summary = getSummary(this);
                        if (summary) {
                            api.setSummary(summary);
                        }
                        return closeAfterDelay().then(() => result);
                    };
                    if (reloadPromise && typeof reloadPromise.then === 'function') {
                        return reloadPromise.then(finalize);
                    }
                    return finalize();
                }).catch((error) => {
                    stopTicker();
                    api.setProgress(100);
                    api.setState(config.failureMessage, { striped: false, stateClass: 'bg-danger' });
                    api.setSummary('');
                    return closeAfterDelay().then(() => {
                        throw error;
                    });
                });
            }
            return this._super.apply(this, arguments);
        },
    });
});
