# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import unicode_literals
import contextlib
import os
import random
import string
import unittest
from datetime import datetime, date

from past.builtins.misc import xrange

from pyathenajdbc import connect
from pyathenajdbc.error import DatabaseError, ProgrammingError, NotSupportedError

from tests.util import with_cursor, Env, read_query


_ENV = Env()
_BASE_PATH = os.path.dirname(os.path.abspath(__file__))
_SCHEMA = 'test_pyathena_jdbc_' + \
          ''.join([random.choice(string.ascii_lowercase + string.digits) for i in range(10)])


def setup_module(module):
    with contextlib.closing(connect()) as conn:
        with conn.cursor() as cursor:
            _create_database(cursor)
            _create_table(cursor)


def teardown_module(module):
    with contextlib.closing(connect()) as conn:
        with conn.cursor() as cursor:
            _drop_database(cursor)


def _create_database(cursor):
    for q in read_query(os.path.join(_BASE_PATH, 'sql', 'create_database.sql')):
        cursor.execute(q.format(schema=_SCHEMA))


def _drop_database(cursor):
    for q in read_query(os.path.join(_BASE_PATH, 'sql', 'drop_database.sql')):
        cursor.execute(q.format(schema=_SCHEMA))


def _create_table(cursor):
    location_one_row = '{0}{1}/{2}/'.format(
        _ENV.s3_staging_dir, 'test_pyathena_jdbc', 'one_row')
    location_many_rows = '{0}{1}/{2}/'.format(
        _ENV.s3_staging_dir, 'test_pyathena_jdbc', 'many_rows')
    location_one_row_complex = '{0}{1}/{2}/'.format(
        _ENV.s3_staging_dir, 'test_pyathena_jdbc', 'one_row_complex')
    for q in read_query(
            os.path.join(_BASE_PATH, 'sql', 'create_table.sql')):
        cursor.execute(q.format(schema=_SCHEMA,
                                location_one_row=location_one_row,
                                location_many_rows=location_many_rows,
                                location_one_row_complex=location_one_row_complex))


class TestPyAthenaJDBC(unittest.TestCase):
    """Reference test case is following:

    https://github.com/dropbox/PyHive/blob/master/pyhive/tests/dbapi_test_case.py
    https://github.com/dropbox/PyHive/blob/master/pyhive/tests/test_hive.py
    https://github.com/dropbox/PyHive/blob/master/pyhive/tests/test_presto.py
    """

    def connect(self):
        return connect(schema_name=_SCHEMA)

    @with_cursor
    def test_fetchone(self, cursor):
        cursor.execute('SELECT * FROM one_row')
        self.assertEqual(cursor.rownumber, 0)
        self.assertEqual(cursor.fetchone(), (1,))
        self.assertEqual(cursor.rownumber, 1)
        self.assertEqual(cursor.fetchone(), None)

    @with_cursor
    def test_fetchall(self, cursor):
        cursor.execute('SELECT * FROM one_row')
        self.assertEqual(cursor.fetchall(), [(1,)])
        cursor.execute('SELECT a FROM many_rows ORDER BY a')
        self.assertEqual(cursor.fetchall(), [(i,) for i in xrange(10000)])

    @with_cursor
    def test_null_param(self, cursor):
        cursor.execute('SELECT {0:s} FROM one_row', None)
        self.assertEqual(cursor.fetchall(), [(None,)])

    @with_cursor
    def test_iterator(self, cursor):
        cursor.execute('SELECT * FROM one_row')
        self.assertEqual(list(cursor), [(1,)])
        self.assertRaises(StopIteration, cursor.__next__)

    @with_cursor
    def test_description_initial(self, cursor):
        self.assertEqual(cursor.description, None)

    @with_cursor
    def test_description_failed(self, cursor):
        try:
            cursor.execute('blah_blah')
        except DatabaseError:
            pass
        self.assertEqual(cursor.description, None)

    @with_cursor
    def test_bad_query(self, cursor):
        def run():
            cursor.execute('SELECT does_not_exist FROM this_really_does_not_exist')
            cursor.fetchone()
        self.assertRaises(DatabaseError, run)

    @with_cursor
    def test_fetchone_no_data(self, cursor):
        self.assertRaises(ProgrammingError, cursor.fetchone)

    @with_cursor
    def test_fetchmany(self, cursor):
        cursor.execute('SELECT * FROM many_rows LIMIT 15')
        self.assertEqual(len(cursor.fetchmany(10)), 10)
        self.assertEqual(len(cursor.fetchmany(10)), 5)

    @with_cursor
    def test_arraysize(self, cursor):
        cursor.arraysize = 5
        cursor.execute('SELECT * FROM many_rows LIMIT 20')
        self.assertEqual(len(cursor.fetchmany()), 5)

    @with_cursor
    def test_no_params(self, cursor):
        self.assertRaises(IndexError, lambda: cursor.execute("SELECT '{0:s}' FROM one_row"))
        self.assertRaises(KeyError, lambda: cursor.execute("SELECT '{x:s}' FROM one_row"))

    def test_escape(self):
        bad_str = '''`~!@#$%^&*()_+-={}[]|\\;:'",./<>?\n\r\t '''
        self.run_escape_case(bad_str)

    @with_cursor
    def run_escape_case(self, cursor, bad_str):
        # TODO Mmmm...
        # Expected: \\ -> \\, \r -> \r
        # Actual:   \\ -> nothing, \r -> \n
        #   - [(1, u'`~!@#$%^&*()_+-={}[]|;:\'",./<>?\n\n\t ')]
        #   ?                                           ^
        #   + [(1, u'`~!@#$%^&*()_+-={}[]|\\;:\'",./<>?\n\r\t ')]
        #   ?                             ++              ^
        expected = '''`~!@#$%^&*()_+-={}[]|;:'",./<>?\n\n\t '''
        cursor.execute('SELECT {0:d}, {1:s} FROM one_row', 1, bad_str)
        self.assertEqual(cursor.fetchall(), [(1, expected,)])
        cursor.execute('SELECT {a:d}, {b:s} FROM one_row', a=1, b=bad_str)
        self.assertEqual(cursor.fetchall(), [(1, expected,)])

    @with_cursor
    def test_none_empty_query(self, cursor):
        self.assertRaises(ProgrammingError, lambda: cursor.execute(None))
        self.assertRaises(ProgrammingError, lambda: cursor.execute(''))

    @with_cursor
    def test_invalid_params(self, cursor):
        self.assertRaises(TypeError, lambda: cursor.execute(
            'SELECT * FROM one_row', {}))

    def test_open_close(self):
        with contextlib.closing(self.connect()):
            pass
        with contextlib.closing(self.connect()) as conn:
            with conn.cursor():
                pass

    @with_cursor
    def test_unicode(self, cursor):
        unicode_str = "王兢"
        cursor.execute('SELECT {0:s} FROM one_row', unicode_str)
        self.assertEqual(cursor.fetchall(), [(unicode_str,)])

    @with_cursor
    def test_null(self, cursor):
        cursor.execute('SELECT null FROM many_rows')
        self.assertEqual(cursor.fetchall(), [(None,)] * 10000)
        cursor.execute('SELECT IF(a % 11 = 0, null, a) FROM many_rows')
        self.assertEqual(cursor.fetchall(), [(None if a % 11 == 0 else a,) for a in xrange(10000)])

    @with_cursor
    def test_description(self, cursor):
        cursor.execute('SELECT 1 AS foobar FROM one_row')
        self.assertEqual(cursor.description, [('foobar', 4, 11, None, 10, 0, 2)])

    @with_cursor
    def test_complex(self, cursor):
        # TODO DECIMAL type failed to fetch with java.lang.IndexOutOfBoundsException
        # https://forums.aws.amazon.com/thread.jspa?threadID=245004
        cursor.execute("""
        SELECT
          col_boolean
          ,col_tinyint
          ,col_smallint
          ,col_int
          ,col_bigint
          ,col_float
          ,col_double
          ,col_string
          ,col_timestamp
          ,col_date
          ,col_binary
          ,col_array
          ,col_map
          ,col_struct
          --,col_decimal
        FROM one_row_complex
        """)
        self.assertEqual(cursor.description, [
            ('col_boolean', 16, 5, None, 0, 0, 2),
            ('col_tinyint', -6, 4, None, 3, 0, 2),
            ('col_smallint', 5, 6, None, 5, 0, 2),
            ('col_int', 4, 11, None, 10, 0, 2),
            ('col_bigint', -5, 20, None, 19, 0, 2),
            ('col_float', 8, 24, None, 17, 0, 2),
            ('col_double', 8, 24, None, 17, 0, 2),
            ('col_string', -16, 1073741824, None, 1073741824, 0, 2),
            ('col_timestamp', 93, 23, None, 3, 0, 2),
            ('col_date', 91, 10, None, 0, 0, 2),
            ('col_binary', -4, 1073741824, None, 1073741824, 0, 2),
            ('col_array', 2003, 0, None, 0, 0, 2),
            ('col_map', 2000, 0, None, 0, 0, 2),
            ('col_struct', 2000, 0, None, 0, 0, 2),
            # ('col_decimal', ???, ???, None, ???, ???, ???),
        ])
        rows = cursor.fetchall()
        expected = [(
            True,
            127,
            32767,
            2147483647,
            9223372036854775807,
            0.5,
            0.25,
            'a string',
            datetime(2017, 1, 1, 0, 0, 0),
            date(2017, 1, 2),
            b'123',
            '[1, 2]',
            '{1=2, 3=4}',
            '{a=1, b=2}',
            # '0.1',
        )]
        self.assertEqual(rows, expected)
        # catch unicode/str
        self.assertEqual(list(map(type, rows[0])), list(map(type, expected[0])))

    # TODO
    # @with_cursor
    # def test_cancel(self, cursor):
    #     from concurrent.futures import ThreadPoolExecutor
    #
    #     def cancel(c):
    #         import jpype
    #         import time
    #         jpype.attachThreadToJVM()
    #         time.sleep(10)
    #         c.cancel()
    #
    #     with ThreadPoolExecutor(max_workers=1) as executor:
    #         executor.submit(cancel, cursor)
    #
    #         self.assertRaises(DatabaseError, lambda:
    #         cursor.execute("""
    #         SELECT a.a * rand(), b.a * rand()
    #         FROM many_rows a
    #         CROSS JOIN many_rows b
    #         """))

    def test_connection_is_closed(self):
        conn = self.connect()
        self.assertEqual(conn.is_closed, False)
        conn.close()
        self.assertEqual(conn.is_closed, True)
        self.assertRaises(ProgrammingError, lambda: conn.cursor())

    def test_cursor_is_closed(self):
        with contextlib.closing(self.connect()) as conn:
            cursor = conn.cursor()
            self.assertEqual(cursor.is_closed, False)
            cursor.close()
            self.assertEqual(cursor.is_closed, True)
            self.assertRaises(ProgrammingError, lambda: cursor.execute(
                'SELECT * FROM one_row'))
            self.assertRaises(ProgrammingError, lambda: cursor.fetchone())
            self.assertRaises(ProgrammingError, lambda: cursor.fetchmany())
            self.assertRaises(ProgrammingError, lambda: cursor.fetchall())
            self.assertRaises(ProgrammingError, lambda: cursor.cancel())

    def test_no_ops(self):
        conn = self.connect()
        cursor = conn.cursor()
        self.assertEqual(cursor.rowcount, -1)
        cursor.setinputsizes([])
        cursor.setoutputsize(1, 'blah')
        self.assertRaises(NotSupportedError, lambda: cursor.executemany(
            'SELECT * FROM one_row', []))
        conn.commit()
        self.assertRaises(NotSupportedError, lambda: conn.rollback())
        cursor.close()
        conn.close()
