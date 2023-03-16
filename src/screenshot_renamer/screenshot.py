"""
Screenshotter
"""

import argparse
from datetime import datetime, timezone
import hashlib
import logging
import os
import pathlib
import re
import shutil
import sys
from time import sleep
from typing import List

import pytz
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent, LoggingEventHandler

from screenshot_renamer import __version__

__author__ = "Jason Nishi"
__copyright__ = "Jason Nishi"
__license__ = "MIT"

_logger = logging.getLogger(__name__)

# ---- Python API ----

class RenamerHandler(FileSystemEventHandler):
    #############################
    #  === CLASS CONSTANTS ===  #
    #############################

    READ_BYTES_FOR_HASH: int = 1048576
    """ Bytes to read to calculate our hash."""

    CONSTRUCT_FN: str = 'Screenshot-{datetime}-{checksum}{ext}'
    """ File name template for constructing new filename """

    USE_DATETIME_TIMEZONE: str = "UTC"
    """ Timezone string to use for file date. """

    VALID_EXTS: List[str] = ['.png', '.jpg', '.jpeg']
    """ Extensions to operate on. """

    VALID_FN: re.Pattern = re.compile(r'Screenshot-'
                                    r'(?P<datetime>[0-9]{8}-[0-9]{6})-'
                                    r'(?P<checksum>[0-9A-Fa-f]{8})'
                                    r'\..*')
    """ Regular expression to check whether file name pattern matches. """

    #####################
    #  === METHODS ===  #
    #####################

    @classmethod
    def needs_rename(cls, path: str) -> bool:
        """Determines whether a file needs to be renamed, according to the
        filename rules in use.

        :param path: Path to the file in question
        :type path: str
        :return: Whether the file needs to be renamed: True if yes, False if no.
        :rtype: bool
        """
        return not bool(cls.VALID_FN.match(os.path.basename(path)))

    @classmethod
    def checksum_partial(cls, path: str) -> str:
        """Calculate a partial checksum of the file, used to help give a unique
        name in case of multiple screenshots.

        :param path: Path to the file in question
        :type path: str
        :return: Partial checksum of the file, calculated from a full checksum
        :rtype: str
        """
        with open(path, 'rb') as fh:
            data = fh.read()
            checksum = hashlib.sha256(data).hexdigest()
        partial = checksum[-8:]
        _logger.debug('%s: SHA-256: %s, partial: %s',
                        path, checksum, partial)
        return partial

    @classmethod
    def file_datetime(cls, path: str) -> str:
        """Generate a date/time string partial for a filename, based on the
        modified time of the time.

        :param path: Path to the file in question
        :type path: str
        :return: date/time string for the file, based out of the timezone
            declared.
        :rtype: str
        """
        mod_time = pathlib.Path(path).stat().st_mtime
        datetime_obj = datetime.fromtimestamp(
            mod_time,
            tz=pytz.timezone(cls.USE_DATETIME_TIMEZONE)
        )
        iso8601_datetime = datetime_obj.isoformat()
        return_datetime = datetime_obj.strftime('%Y%m%d-%H%M%S')
        _logger.debug('%s: Modified Date/Time: %s, Filename Partial: %s',
                    path, iso8601_datetime, return_datetime)
        return return_datetime

    def new_filename(self, path: str) -> str:
        """Generate a new filename for a given file, given the current filename.

        :param path: Path to the file in question.
        :type path: str
        :return: The new filename to give the file.
        :rtype: str
        """
        file_date = self.file_datetime(path)
        file_cksum = self.checksum_partial(path)
        ext = os.path.splitext(os.path.basename(path))[-1]
        return self.CONSTRUCT_FN.format(datetime=file_date, checksum=file_cksum, ext=ext)

    def rename(self, path: str, new_filename: str) -> bool:
        """rename _summary_

        :param path: Path of the file in question.
        :type path: str
        :param new_filename: New filename to give the file.
        :type new_filename: str
        :return: Whether the file rename was successful.
        :rtype: bool
        """

        new_path = os.path.join(os.path.dirname(path), new_filename)
        if os.path.exists(new_path):
            _logger.error('File %s -> %s already exists, cannot move.',
                        path, new_path)
            return False
        
        # @TODO: Exception handling.
        if os.path.exists(path):
            shutil.move(path, new_path)
        _logger.info('Moved: %s -> %s', path, new_path)
        return True

    def handle_event(self, event: FileSystemEvent) -> bool:
        """Take care of handling any file system event we're concerned with.

        :param event: The event from the file system.
        :type event: FileSystemEvent
        :return: Whether the event did any renaming.
        :rtype: bool
        """
        path = event.src_path
        if event.is_directory:
            _logger.debug('%s: Is a directory, not operating.', path)
            return False

        file_ext = os.path.splitext(os.path.basename(path))[-1].lower().strip()
        if file_ext not in self.VALID_EXTS:
            _logger.debug('%s: Not an extension of concern, not operating.', path)
            return False

        if not self.needs_rename(path):
            _logger.debug('%s: File already meets correct pattern, no action '
                          'needed.', path)
            return False

        _logger.debug('Sleeping for 1 second before rename.')
        sleep(1)
        new_fn = self.new_filename(path)
        return self.rename(path, new_fn)

    def on_created(self, event: FileSystemEvent) -> bool:
        """Fires when a file/directory is created, handles renaming files as
        needed.

        :param event: Event describing the action that occurred. Should likely
            be a FileCreatedEvent or a DirCreatedEvent.
        :type event: FileSystemEvent
        :return: Whether the event handler needed to take care of anything.
        :rtype: bool
        """
        _logger.info('File creation detected: %s', event.src_path)
        return self.handle_event(event)

##############################################################################


def handle_monitoring(paths: List[str], recursive: bool) -> bool:
    """handle_monitoring _summary_

    :param paths: _description_
    :type paths: List[str]
    :param recursive: _description_
    :type recursive: bool
    :return: ``True`` upon completion.
    :rtype: bool
    """
    event_handler = RenamerHandler()
    # event_handler = LoggingEventHandler()
    observer = Observer()
    for cur_path in paths:
        if os.path.isdir(cur_path):
            use_recursive = recursive
        elif os.path.isfile(cur_path):
            use_recursive = False  # meaningless for files.
        else:
            _logger.error('%s: not a directory or file, skipping.')
            continue

        _logger.info('%s: Scheduling for watch.', cur_path)
        observer.schedule(event_handler, cur_path, recursive=use_recursive)

    print('Watching paths, Use CTRL-C to stop.')

    observer.start()
    _logger.debug(observer)
    _logger.debug(observer.is_alive())

    try:
        while observer.is_alive():
            observer.join(1)
    finally:
        _logger.debug('CTRL-C detected, closing out.')
        observer.stop()
        observer.join()
        return True

# ---- CLI ----
# The functions defined in this section are wrappers around the main Python
# API allowing them to be called directly from the terminal as a CLI
# executable/script.


def parse_args(args: List[str]) -> argparse.Namespace:
    """Parse arguments from CLI

    :param args: List of arguments from CLI
    :type args: List[str]
    :return: parsed arguments.
    :rtype: argparse.Namespace
    """
    parser = argparse.ArgumentParser(description="__name__")

    parser.add_argument("watch_paths",
                        action="store",
                        nargs="+",
                        type=str,
                        help="Paths to watch.",
                        metavar='FILE_OR_DIRECTORY')

    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="When set, will monitor folders recursively.",
        dest="recursive",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"ScreenshotRenamer {__version__}",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        dest="loglevel",
        help="set loglevel to INFO",
        action="store_const",
        const=logging.INFO,
    )
    parser.add_argument(
        "-vv",
        "--very-verbose",
        dest="loglevel",
        help="set loglevel to DEBUG",
        action="store_const",
        const=logging.DEBUG,
    )
    return parser.parse_args(args)


def setup_logging(loglevel):
    """Setup basic logging

    Args:
      loglevel (int): minimum loglevel for emitting messages
    """
    logformat = "[%(asctime)s] %(levelname)s:%(name)s:%(message)s"
    logging.basicConfig(
        level=loglevel, stream=sys.stdout, format=logformat, datefmt="%Y-%m-%d %H:%M:%S"
    )


def main(args: List[str]) -> int:
    """Wrapper allowing :func:`fib` to be called with string arguments in a CLI fashion

    Instead of returning the value from :func:`fib`, it prints the result to the
    ``stdout`` in a nicely formatted message.

    :param args:  command line parameters as list of strings
          (for example  ``["--verbose", "42"]``).
    :type args: List[str]
    :return: Exit code to return for application.
    :rtype: int
    """
    args = parse_args(args)
    setup_logging(args.loglevel)
    _logger.info("Starting up monitoring.")
    handle_monitoring(args.watch_paths, args.recursive)
    _logger.info("Ending monitoring.")
    return 0


def run():
    """Calls :func:`main` passing the CLI arguments extracted from :obj:`sys.argv`

    This function can be used as entry point to create console scripts with setuptools.
    """
    sys.exit(main(sys.argv[1:]))


if __name__ == "__main__":
    run()
