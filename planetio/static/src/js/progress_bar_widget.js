odoo.define('planetio.ProgressBarWidget', function (require) {
    'use strict';

    const AbstractField = require('web.AbstractField');
    const fieldRegistry = require('web.field_registry');
    const core = require('web.core');

    const qweb = core.qweb;

    const ProgressBarWidget = AbstractField.extend({
        supportedFieldTypes: ['float', 'integer'],
        className: 'o_field_progressbar',

        isSet: function () {
            return this.value !== false && this.value !== undefined && this.value !== null;
        },

        _render: function () {
            const value = this.value || 0;
            const percentage = Math.min(100, Math.max(0, value));
            const displayValue = Math.round(percentage);
            this.$el.toggleClass('o_field_empty', !this.isSet());
            this.$el.html(qweb.render('planetio.ProgressBarWidget', {
                value: displayValue,
                percentage: percentage,
            }));
        },
    });

    fieldRegistry.add('progressbar', ProgressBarWidget);

    return ProgressBarWidget;
});
