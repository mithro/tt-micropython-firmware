'''
Created on Nov 20, 2026

Cycle through a list of projects on a timer, as configured by
listing several projects in config.ini, e.g.

    [DEFAULT]
    project = tt_um_a, tt_um_b, tt_um_c
    switch_interval = 15

The rotation is available through the demoboard, as
    tt.project_rotation.stop()
    tt.project_rotation.start()
    tt.project_rotation.next()

Enabling any project by hand (e.g. tt.shuttle.tt_um_x.enable())
stops the rotation.

@author: Tim 'mithro' Ansell
'''
from ttboard.pins.upython import Timer
import ttboard.log as logging
log = logging.getLogger(__name__)


class ProjectRotation:
    DefaultIntervalSeconds = 15

    def __init__(self, shuttle, project_names: list, interval_s,
                 timer_class=Timer):
        '''
            shuttle: the project mux (tt.shuttle)
            project_names: projects to cycle through, in order; the
                first one is expected to be enabled already
            interval_s: seconds each project stays enabled
        '''
        self._shuttle = shuttle
        self.projects = list(project_names)
        self.interval_s = interval_s
        self._timer_class = timer_class
        self._timer = None
        self._index = 0
        # True while we are the ones enabling a project, so the
        # demoboard can tell our switches apart from manual ones
        self.switching = False

    @property
    def running(self) -> bool:
        return self._timer is not None

    @property
    def current(self) -> str:
        return self.projects[self._index]

    def start(self):
        if self.running:
            return
        if len(self.projects) < 2:
            log.info('Project rotation needs at least two projects, not starting')
            return
        if self.interval_s is None or self.interval_s <= 0:
            log.info('Project rotation switch_interval is 0, not starting')
            return
        log.info(f'Rotating through {len(self.projects)} projects every {self.interval_s}s')
        self._timer = self._timer_class()
        self._timer.init(period=int(self.interval_s * 1000),
                         mode=self._timer_class.PERIODIC,
                         callback=self._on_timer)

    def stop(self):
        if self._timer is None:
            return
        log.info('Stopping project rotation')
        self._timer.deinit()
        self._timer = None

    def next(self) -> bool:
        '''
            Enable the next project in the list, skipping any that
            fail to enable (e.g. due to their danger level).
            Returns True if a project was enabled.
        '''
        for _attempt in range(len(self.projects)):
            self._index = (self._index + 1) % len(self.projects)
            name = self.current
            if self._enable(name):
                return True
            log.warn(f'Project rotation: could not enable "{name}", skipping')
        return False

    def _enable(self, name: str) -> bool:
        self.switching = True
        try:
            return bool(self._shuttle.get(name).enable())
        finally:
            self.switching = False

    def _on_timer(self, _timer):
        # an exception escaping a machine.Timer callback would
        # stop the timer, so log it and carry on
        try:
            self.next()
        except Exception as e:
            log.error(f'Project rotation error: {e}')

    def __repr__(self):
        state = 'running' if self.running else 'stopped'
        return f'<ProjectRotation {state}, every {self.interval_s}s: {", ".join(self.projects)}>'
